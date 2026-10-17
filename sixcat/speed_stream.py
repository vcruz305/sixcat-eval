"""Client-observed streaming speed measurements and capability evidence.

Receipts contain counts and timings, never prompt or generated response content.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any

_UNSET = object()
_SUCCESS_FINISH_REASONS = {"stop", "length", "eos", "eos_token", "max_tokens", "stop_sequence"}
_LIMIT_FINISH_REASONS = {"length", "max_tokens"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _count(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(value)


def _positive(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            part["text"] for part in value
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _parts_from_chunk(chunk: dict) -> tuple[str, str]:
    choices = chunk.get("choices") or []
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "", ""
    choice = choices[0]
    delta = _mapping(choice.get("delta", choice.get("message")))
    reasoning = ""
    for key in ("reasoning_content", "reasoning", "thinking"):
        reasoning = _text(delta.get(key))
        if reasoning:
            break
    content = _text(delta.get("content")) or _text(choice.get("text"))
    return reasoning, content


def _content_from_chunk(chunk: dict) -> str:
    reasoning, content = _parts_from_chunk(chunk)
    return reasoning + content


def _policy_payload(client: Any, prompt: str, max_tokens: int) -> dict:
    policy = client.policy
    request_params = {"temperature": policy.temperature}
    for key in ("top_p", "top_k", "min_p"):
        value = getattr(policy, key, None)
        if value is not None:
            request_params[key] = value
    request_params.update(_mapping(policy.to_dict().get("extra")))
    # A legacy preclose policy must not silently contradict the requested mode.
    request_params.pop("enable_thinking", None)
    request_params.pop("preclose_think", None)
    template_kwargs = dict(_mapping(request_params.pop("chat_template_kwargs", None)))
    template_kwargs["enable_thinking"] = bool(policy.thinking)
    effort = request_params.get("reasoning_effort")
    if effort is not None:
        template_kwargs["reasoning_effort"] = effort
    return {
        **request_params,
        "model": client.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "chat_template_kwargs": template_kwargs,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


class _StreamInvalid(Exception):
    """A safe, content-free protocol failure description."""


class _UnsupportedOption(Exception):
    def __init__(self, option: str):
        self.option = option


class _ReasoningTracker:
    """Classify separate reasoning and common, possibly split, think markers."""

    def __init__(self):
        self.first_answer: float | None = None
        self.saw_reasoning = False
        self.saw_markers = False
        self.in_think = False
        self.saw_open = False
        self.saw_close = False
        self.separate_reasoning = False
        self.regular_text_seen = False
        self.pending = ""
        self.pending_at: float | None = None

    def _record(self, text: str, when: float) -> None:
        if not text:
            return
        if self.in_think:
            if text.strip():
                self.saw_reasoning = True
        else:
            if text.strip() and self.first_answer is None:
                self.first_answer = when
            if text.strip():
                self.regular_text_seen = True

    def feed(self, reasoning: str, content: str, when: float) -> None:
        if reasoning:
            self.separate_reasoning = True
            if reasoning.strip():
                self.saw_reasoning = True
        if not content:
            return
        buffer = self.pending + content
        origin = self.pending_at if self.pending else when
        self.pending = ""
        self.pending_at = None
        while buffer:
            positions = [
                (position, marker) for marker in ("<think>", "</think>")
                if (position := buffer.find(marker)) >= 0
            ]
            if positions:
                position, marker = min(positions)
                before = buffer[:position]
                if (
                    marker == "</think>" and not self.saw_open
                    and not self.saw_close and not self.separate_reasoning
                ):
                    # Templates can pre-open <think>. Reclassify earlier bare
                    # content when its first closing marker becomes observable.
                    if self.regular_text_seen or before.strip():
                        self.saw_reasoning = True
                    self.first_answer = None
                else:
                    self._record(before, origin)
                self.saw_markers = True
                self.in_think = marker == "<think>"
                self.saw_open |= marker == "<think>"
                self.saw_close |= marker == "</think>"
                buffer = buffer[position + len(marker):]
                origin = when
                continue
            # Retain only a possible split marker, never the generated body.
            keep = 0
            for marker in ("<think>", "</think>"):
                for length in range(1, len(marker)):
                    if buffer.endswith(marker[:length]):
                        keep = max(keep, length)
            self._record(buffer[:-keep] if keep else buffer, origin)
            if keep:
                self.pending = buffer[-keep:]
                self.pending_at = when
            break


def _merge_metadata(target: dict, update: Any) -> None:
    if not isinstance(update, dict):
        return
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key].update(value)
        else:
            target[key] = value


def _sample_from_stream(
    *,
    started: float,
    first_output: float | None,
    ended: float,
    usage: dict,
    timings: dict,
    metrics: dict,
    meta_info: dict,
    chunks: int,
    compatibility_mode: str,
    last_output: float | None = None,
    first_answer: Any = _UNSET,
    content_chunks: int | None = None,
    thinking_requested: bool | None = None,
    reasoning_streamed: bool = False,
    reasoning_markers: bool = False,
    reasoning_visibility: str = "auto",
    first_chunk_tokens: int | None = None,
    first_chunk_token_source: str | None = None,
    finish_reason: str | None = None,
    generation_completed: bool = True,
    terminal_evidence: list[str] | None = None,
    error: str | None = None,
) -> dict:
    """Convert stream boundaries into qualified measurements.

    Direct legacy callers retain the old signature. Actual stream callers
    always supply last_output and content_chunks explicitly.
    """
    usage, timings, metrics, meta_info = map(_mapping, (usage, timings, metrics, meta_info))
    completion_details = _mapping(usage.get("completion_tokens_details"))
    prompt_details = _mapping(usage.get("prompt_tokens_details"))
    prompt_tokens = _count(usage.get("prompt_tokens"))
    prompt_source = "usage" if prompt_tokens is not None else None
    completion_tokens = _count(usage.get("completion_tokens"))
    completion_source = "usage" if completion_tokens is not None else None

    if prompt_tokens is None:
        evaluated, cached = _count(timings.get("prompt_n")), _count(timings.get("cache_n"))
        if evaluated is not None:
            prompt_tokens, prompt_source = evaluated + (cached or 0), "native_timings"
        else:
            prompt_tokens = _count(meta_info.get("prompt_tokens"))
            if prompt_tokens is not None:
                prompt_source = "provider_meta_info"
    if completion_tokens is None:
        completion_tokens = _count(timings.get("predicted_n"))
        if completion_tokens is not None:
            completion_source = "native_timings"
        else:
            completion_tokens = _count(meta_info.get("completion_tokens"))
            if completion_tokens is not None:
                completion_source = "provider_meta_info"

    cached_prompt_tokens = _count(prompt_details.get("cached_tokens"))
    if cached_prompt_tokens is None:
        cached_prompt_tokens = _count(meta_info.get("cached_tokens"))
    if cached_prompt_tokens is None:
        cached_prompt_tokens = _count(timings.get("cache_n"))
    reasoning_tokens = _count(completion_details.get("reasoning_tokens"))
    if reasoning_tokens is None:
        reasoning_tokens = _count(usage.get("reasoning_tokens"))
    if reasoning_tokens is None:
        reasoning_tokens = _count(meta_info.get("reasoning_tokens"))
    answer_tokens = _count(completion_details.get("answer_tokens"))
    if answer_tokens is None:
        answer_tokens = _count(completion_details.get("text_tokens"))
    reasoning_count_inconsistent = (
        completion_tokens is not None and reasoning_tokens is not None
        and reasoning_tokens > completion_tokens
    )
    if (
        completion_tokens is not None and reasoning_tokens is not None
        and answer_tokens is not None
        and reasoning_tokens + answer_tokens > completion_tokens
    ):
        reasoning_count_inconsistent = True
    if (
        answer_tokens is None and completion_tokens is not None
        and reasoning_tokens is not None and not reasoning_count_inconsistent
    ):
        answer_tokens = completion_tokens - reasoning_tokens
    if answer_tokens is not None and completion_tokens is not None and answer_tokens > completion_tokens:
        answer_tokens = None
        reasoning_count_inconsistent = True

    hidden_reported = reasoning_tokens is not None and reasoning_tokens > 0 and not reasoning_streamed
    hidden = hidden_reported or reasoning_visibility == "hidden"
    if reasoning_streamed:
        reasoning_observation = "streamed"
    elif hidden_reported:
        reasoning_observation = "hidden_reported"
    elif reasoning_tokens == 0:
        reasoning_observation = "none_reported"
    elif reasoning_markers:
        reasoning_observation = "markers_only_unverified"
    else:
        reasoning_observation = "unverified"
    unverified = reasoning_observation in {"unverified", "markers_only_unverified"}
    last_output = last_output if last_output is not None else (ended if first_output is not None else None)
    generation_chunks = chunks if content_chunks is None else content_chunks
    if first_answer is _UNSET:
        first_answer = None if reasoning_streamed else first_output
    # A template may pre-open thinking and hit its cap without a closing
    # marker. Bare, unverified thinking-on text is not proof an answer began.
    answer_boundary_unverified = (
        thinking_requested is True and unverified and not reasoning_markers
        and reasoning_visibility != "hidden"
    )
    if answer_boundary_unverified:
        first_answer = None

    ttft = max(0.0, first_output - started) if first_output is not None else None
    ttfo = max(0.0, first_answer - started) if first_answer is not None else None
    e2e = max(0.0, last_output - started) if last_output is not None else None
    stream_end = max(0.0, ended - started)
    decode_seconds = (
        last_output - first_output if first_output is not None and last_output is not None else None
    )
    ok = first_output is not None and generation_completed and error is None

    first_chunk_tokens = _count(first_chunk_tokens) or None
    corrected_first_count = first_chunk_tokens or 1
    first_chunk_source = (
        (first_chunk_token_source or "provider_cumulative_usage")
        if first_chunk_tokens is not None else "assumed_one_token"
    )
    decode_tps = prefill_tps = tpot = None
    if not ok:
        prefill_status = decode_status = "incomplete_stream"
    elif hidden:
        prefill_status = decode_status = "hidden_reasoning"
    elif reasoning_count_inconsistent:
        prefill_status = decode_status = "inconsistent_reasoning_token_count"
    else:
        if prompt_tokens is None:
            prefill_status = "missing_prompt_tokens"
        elif ttft is None or ttft <= 0:
            prefill_status = "nonpositive_ttft"
        else:
            prefill_tps = prompt_tokens / ttft
            prefill_status = "unverified_reasoning_visibility" if unverified else "ok"
        if completion_tokens is None:
            decode_status = "missing_completion_tokens"
        elif completion_tokens < 2:
            decode_status = "insufficient_tokens"
        elif generation_chunks < 2:
            decode_status = "buffered_output"
        elif decode_seconds is None or decode_seconds <= 0:
            decode_status = "nonpositive_generation_interval"
        elif corrected_first_count >= completion_tokens:
            decode_status = "insufficient_post_first_chunk_tokens"
        else:
            remaining_tokens = completion_tokens - corrected_first_count
            decode_tps, tpot = remaining_tokens / decode_seconds, decode_seconds / remaining_tokens
            decode_status = (
                "unverified_reasoning_visibility" if unverified
                else ("ok" if first_chunk_tokens is not None else "approximate_first_chunk")
            )

    provider_ttft = _positive(metrics.get("time_to_first_token_ms"))
    provider_ttft = provider_ttft / 1000.0 if provider_ttft is not None else _positive(meta_info.get("ttft"))
    provider_generation = _positive(metrics.get("generation_time_ms"))
    if provider_generation is not None:
        provider_generation /= 1000.0
    provider_queue = _number(metrics.get("queue_time_ms"))
    provider_queue = provider_queue / 1000.0 if provider_queue is not None and provider_queue >= 0 else None
    provider_mean_itl = _positive(metrics.get("mean_itl_ms"))
    provider_mean_itl = provider_mean_itl / 1000.0 if provider_mean_itl is not None else _positive(meta_info.get("tpot"))
    provider_effective_prefill = (
        prompt_tokens / provider_ttft if prompt_tokens is not None and provider_ttft is not None else None
    )
    provider_effective_decode = None
    if completion_tokens is not None and completion_tokens > 1:
        if provider_generation is not None:
            provider_effective_decode = (completion_tokens - 1) / provider_generation
        elif _positive(meta_info.get("tpot")) is not None:
            provider_effective_decode = 1.0 / meta_info["tpot"]

    sources = sorted({source for source in (prompt_source, completion_source) if source})
    if hidden:
        ttft_kind = "first_visible_output_after_hidden_reasoning"
    elif unverified:
        ttft_kind = "first_observed_output_unverified_reasoning"
    else:
        ttft_kind = "first_observed_generation"
    return {
        "ok": ok, "error": error, "error_type": error,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens, "answer_tokens": answer_tokens,
        "cached_prompt_tokens": cached_prompt_tokens,
        "token_count_source": "+".join(sources) if sources else "unavailable",
        "prompt_token_count_source": prompt_source,
        "completion_token_count_source": completion_source,
        "client_ttft_s": ttft, "client_ttft_kind": ttft_kind,
        "client_ttfo_s": ttfo, "first_answer_s": ttfo,
        "ttfo_metric_status": "unverified_answer_boundary" if answer_boundary_unverified else ("observed" if ttfo is not None else "not_observed"),
        "e2e_s": e2e, "stream_end_s": stream_end,
        "decode_s": decode_seconds, "client_generation_s": decode_seconds,
        "tpot_s": tpot, "client_tpot_s": tpot,
        "effective_prefill_tps": prefill_tps, "effective_decode_tps": decode_tps,
        "prefill_metric_status": prefill_status, "decode_metric_status": decode_status,
        "thinking_requested": thinking_requested,
        "reasoning_visibility_declared": reasoning_visibility,
        "reasoning_observation": reasoning_observation,
        "reasoning_streamed": reasoning_streamed,
        "reasoning_markers_observed": reasoning_markers,
        "hidden_reasoning_reported": hidden_reported,
        "first_chunk_tokens": first_chunk_tokens,
        "first_chunk_token_source": first_chunk_source,
        "first_chunk_count_is_approximate": first_chunk_tokens is None,
        "chunks": chunks, "content_chunks": generation_chunks,
        "finish_reason": finish_reason,
        "output_limit_reached": finish_reason in _LIMIT_FINISH_REASONS,
        "generation_completed": generation_completed,
        "terminal_evidence": terminal_evidence or [],
        "compatibility_mode": compatibility_mode,
        "server_prefill_tps": _positive(timings.get("prompt_per_second")),
        "server_decode_tps": _positive(timings.get("predicted_per_second")),
        "provider_ttft_s": provider_ttft, "provider_generation_s": provider_generation,
        "provider_queue_s": provider_queue, "provider_mean_itl_s": provider_mean_itl,
        "provider_tokens_per_second": _positive(metrics.get("tokens_per_second")),
        "provider_effective_prefill_tps": provider_effective_prefill,
        "provider_effective_decode_tps": provider_effective_decode,
    }


def _decode_event(data: str, event_name: str) -> dict | str:
    if event_name == "error":
        raise _StreamInvalid("server_error_event")
    if data.strip() == "[DONE]":
        return "[DONE]"
    try:
        chunk = json.loads(data)
    except (json.JSONDecodeError, ValueError):
        raise _StreamInvalid("malformed_sse_json") from None
    if not isinstance(chunk, dict):
        raise _StreamInvalid("non_object_sse_payload")
    if "error" in chunk and chunk["error"] is not None:
        raise _StreamInvalid("server_error_payload")
    return chunk


def _complete_json(data: str) -> bool:
    if data.strip() == "[DONE]":
        return True
    try:
        json.loads(data)
    except (ValueError, json.JSONDecodeError):
        return False
    return True


async def _sse_events(response: Any):
    pending: list[str] = []
    event_name = ""
    last_data_at = time.perf_counter()
    async for line in response.aiter_lines():
        if not line:
            if pending:
                yield _decode_event("\n".join(pending), event_name), last_data_at
                pending = []
            elif event_name == "error":
                raise _StreamInvalid("server_error_event")
            event_name = ""
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        # Accommodate common one-object-per-line producers without blank lines;
        # incomplete JSON remains buffered until its multiline event is complete.
        if pending and _complete_json("\n".join(pending)):
            yield _decode_event("\n".join(pending), event_name), last_data_at
            pending = []
            event_name = ""
        pending.append(line[5:].lstrip(" "))
        last_data_at = time.perf_counter()
    if pending:
        yield _decode_event("\n".join(pending), event_name), last_data_at
    elif event_name == "error":
        raise _StreamInvalid("server_error_event")


def _unsupported_option(status_code: int, body: bytes) -> str | None:
    if status_code not in (400, 422):
        return None
    description = body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(description)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        # Inspect the error, not echoed request parameters elsewhere in a body.
        description = json.dumps(parsed.get("error", parsed.get("detail", parsed)))
    description = description.lower()
    rejection = any(phrase in description for phrase in (
        "unknown", "unsupported", "not supported", "unrecognized", "unexpected",
        "extra_forbidden", "extra inputs are not permitted", "not permitted", "not allowed",
    ))
    if not rejection:
        return None
    if "continuous_usage_stats" in description:
        return "continuous_usage_stats"
    if "stream_options" in description:
        return "stream_options"
    return None


async def _stream_one(
    http: Any, client: Any, prompt: str, *, max_tokens: int,
    timeout_s: float, capabilities: dict | None = None,
) -> dict:
    if capabilities is None:
        capabilities = dict(getattr(client, "speed_options", {}) or {})
    options = dict(getattr(client, "speed_options", {}) or {})
    options.update(capabilities)
    visibility = options.get("reasoning_visibility", "auto")
    if visibility not in {"auto", "streamed", "hidden"}:
        raise ValueError("reasoning_visibility must be auto, streamed, or hidden")
    requested_continuous = bool(options.get("per_chunk_usage", False))
    started = time.perf_counter()
    deadline = started + timeout_s
    payload = _policy_payload(client, prompt, max_tokens)
    headers = {"Authorization": f"Bearer {client.api_key}"}
    tracker = _ReasoningTracker()
    usage, timings, metrics, meta_info = {}, {}, {}, {}
    first_output = last_output = first_chunk_tokens = first_chunk_source = None
    chunks = content_chunks = 0
    finish_reason = None
    done = False
    protocol_error = None
    compatibility_mode = "include_usage"
    terminal_evidence: list[str] = []

    # Option negotiation and response cleanup share one absolute timeout.
    async with asyncio.timeout(timeout_s):
        while True:
            if capabilities.get("stream_options_supported", True):
                payload["stream_options"] = {"include_usage": True}
                compatibility_mode = "include_usage"
                if requested_continuous and capabilities.get("continuous_usage_stats_supported", True):
                    payload["stream_options"]["continuous_usage_stats"] = True
                    compatibility_mode = "continuous_usage_stats"
            else:
                payload.pop("stream_options", None)
                compatibility_mode = "without_stream_options"
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError("speed request deadline exceeded")
            try:
                async with http.stream(
                    "POST", client.base_url.rstrip("/") + "/chat/completions",
                    json=payload, headers=headers, timeout=remaining,
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        unsupported = _unsupported_option(response.status_code, body)
                        if (
                            unsupported == "continuous_usage_stats"
                            and payload.get("stream_options", {}).get("continuous_usage_stats")
                        ):
                            raise _UnsupportedOption(unsupported)
                        if unsupported == "stream_options" and "stream_options" in payload:
                            raise _UnsupportedOption(unsupported)
                        response.raise_for_status()
                    async for chunk, received_at in _sse_events(response):
                        if chunk == "[DONE]":
                            done = True
                            terminal_evidence.append("done")
                            break
                        chunks += 1
                        for name, target in (
                            ("usage", usage), ("timings", timings),
                            ("metrics", metrics), ("meta_info", meta_info),
                        ):
                            _merge_metadata(target, chunk.get(name))
                        choices = chunk.get("choices", [])
                        if not isinstance(choices, list):
                            raise _StreamInvalid("invalid_choices")
                        if len(choices) > 1:
                            raise _StreamInvalid("multiple_choices_unsupported")
                        finished_before_chunk = finish_reason is not None
                        if choices:
                            choice = choices[0]
                            if not isinstance(choice, dict):
                                raise _StreamInvalid("invalid_choice")
                            delta = choice.get("delta", choice.get("message", {}))
                            if delta is not None and not isinstance(delta, dict):
                                raise _StreamInvalid("invalid_delta")
                            for field in ("content", "reasoning_content", "reasoning", "thinking"):
                                value = _mapping(delta).get(field)
                                if value is not None and not isinstance(value, (str, list)):
                                    raise _StreamInvalid("invalid_generated_content")
                            reason = choice.get("finish_reason")
                            if reason is not None:
                                if not isinstance(reason, str):
                                    raise _StreamInvalid("invalid_finish_reason")
                                finish_reason = reason
                                if reason in _SUCCESS_FINISH_REASONS:
                                    evidence = "finish_reason:" + reason
                                    if evidence not in terminal_evidence:
                                        terminal_evidence.append(evidence)
                        reasoning, content = _parts_from_chunk(chunk)
                        if reasoning or content:
                            if finished_before_chunk:
                                raise _StreamInvalid("output_after_finish")
                            content_chunks += 1
                            if first_output is None:
                                first_output = received_at
                                first_chunk_tokens = _count(_mapping(chunk.get("usage")).get("completion_tokens"))
                                if first_chunk_tokens:
                                    first_chunk_source = "usage.completion_tokens_cumulative"
                            last_output = received_at
                            tracker.feed(reasoning, content, received_at)
                break
            except _UnsupportedOption as rejected:
                key = (
                    "continuous_usage_stats_supported"
                    if rejected.option == "continuous_usage_stats" else "stream_options_supported"
                )
                capabilities[key] = False
                continue
            except _StreamInvalid as invalid:
                protocol_error = str(invalid)
                break

    ended = time.perf_counter()
    valid_finish = finish_reason in _SUCCESS_FINISH_REASONS
    unsupported_finish = finish_reason is not None and not valid_finish
    completed = protocol_error is None and not unsupported_finish and (done or valid_finish)
    if protocol_error is None:
        if unsupported_finish:
            protocol_error = "unsupported_finish_reason"
        elif not completed:
            protocol_error = "incomplete_stream_no_terminal_evidence"
        elif first_output is None:
            protocol_error = "no_generated_output"
    return _sample_from_stream(
        started=started, first_output=first_output, ended=ended,
        last_output=last_output, first_answer=tracker.first_answer,
        usage=usage, timings=timings, metrics=metrics, meta_info=meta_info,
        chunks=chunks, content_chunks=content_chunks,
        compatibility_mode=compatibility_mode,
        thinking_requested=bool(client.policy.thinking),
        reasoning_streamed=tracker.saw_reasoning,
        reasoning_markers=tracker.saw_markers,
        reasoning_visibility=visibility,
        first_chunk_tokens=first_chunk_tokens,
        first_chunk_token_source=first_chunk_source,
        finish_reason=finish_reason, generation_completed=completed,
        terminal_evidence=terminal_evidence, error=protocol_error,
    )
