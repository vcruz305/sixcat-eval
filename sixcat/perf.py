"""Unscored serving-speed probes and concurrency curve discovery.

The speed path deliberately uses synthetic prompts that begin with unique markers,
so it does not pre-warm SixCat's scored questions or create a large shared prefix.
Client-observed TTFT includes network + queue + prefill. Provider/server metrics are
kept separately when the OpenAI-compatible endpoint exposes them.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any

import httpx

from .client import ChatClient, fetch_server_props
from .journal import TimeBudget
from .policy import custom_policy, override_thinking, resolve_policy
from .storage import atomic_write_json

SPEED_SCHEMA = "sixcat-speed-v1"
CURVE_METHOD = "smallest-concurrency-within-90pct-peak-v1"
DEFAULT_CANDIDATES = (1, 2, 4, 8)
DEFAULT_PROMPT_WORDS = 256
DEFAULT_MAX_TOKENS = 96
DEFAULT_CURVE_SECONDS = 60.0
DEFAULT_CONFIRM_SAMPLES = 32


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = pct * (len(ordered) - 1)
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    fraction = position - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * fraction


def _distribution(values: list[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"n": 0, "min": None, "p5": None, "p50": None, "p95": None, "p99": None, "max": None, "mean": None}
    return {
        "n": len(clean),
        "min": min(clean),
        "p5": _percentile(clean, 0.05),
        "p50": _percentile(clean, 0.50),
        "p95": _percentile(clean, 0.95),
        "p99": _percentile(clean, 0.99),
        "max": max(clean),
        "mean": statistics.fmean(clean),
    }


def parse_candidates(value: str | list[int] | tuple[int, ...]) -> list[int]:
    if isinstance(value, str):
        try:
            candidates = [int(part.strip()) for part in value.split(",") if part.strip()]
        except ValueError as exc:
            raise ValueError("concurrency candidates must be comma-separated positive integers") from exc
    else:
        candidates = [int(item) for item in value]
    if not candidates or any(item < 1 or item > 256 for item in candidates):
        raise ValueError("concurrency candidates must be between 1 and 256")
    candidates = sorted(set(candidates))
    if candidates[0] != 1:
        candidates.insert(0, 1)
    return candidates


def _policy_payload(client: ChatClient, prompt: str, max_tokens: int) -> dict[str, Any]:
    request_params: dict[str, Any] = {
        "temperature": client.policy.temperature,
        "max_tokens": max_tokens,
        "enable_thinking": client.policy.thinking,
    }
    for key in ("top_p", "top_k", "min_p"):
        value = getattr(client.policy, key)
        if value is not None:
            request_params[key] = value
    request_params.update(client.policy.to_dict()["extra"])

    template_kwargs: dict[str, Any] = {"enable_thinking": client.policy.thinking}
    if request_params.pop("preclose_think", False):
        template_kwargs["enable_thinking"] = False
    effort = client.policy.extra.get("reasoning_effort")
    if effort is not None:
        template_kwargs["reasoning_effort"] = effort

    payload: dict[str, Any] = {
        "model": client.model,
        "messages": [{"role": "user", "content": prompt}],
        **{key: value for key, value in request_params.items() if key != "enable_thinking"},
        "chat_template_kwargs": template_kwargs,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    return payload


def synthetic_prompt(*, concurrency: int, index: int, words: int, probe_id: str, phase: str) -> str:
    # The unique marker comes first so prefix caches cannot reuse the large probe body,
    # including between warmup/curve/confirmation phases or separate SixCat invocations.
    marker = (
        f"SIXCAT-SPEED-{probe_id}-{phase}-C{concurrency}-I{index}-"
        f"X{(concurrency * 7919 + index * 104729) % 1_000_003}"
    )
    phrase = "amber cedar cobalt delta ember frost granite harbor iris juniper kinetic lunar"
    tokens = phrase.split()
    body = " ".join(tokens[pos % len(tokens)] for pos in range(words))
    return (
        f"[{marker}] This is an unscored synthetic serving-speed probe. "
        "Read the entire payload. Then emit a long sequence of simple lowercase words "
        "separated by spaces until the server stops generation; do not stop early and "
        "do not answer any benchmark question.\n\n"
        f"payload: {body}"
    )


def _content_from_chunk(chunk: dict[str, Any]) -> str:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
    for key in ("content", "reasoning_content", "reasoning"):
        value = delta.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _sample_from_stream(
    *,
    started: float,
    first_output: float | None,
    ended: float,
    usage: dict[str, Any],
    timings: dict[str, Any],
    metrics: dict[str, Any],
    meta_info: dict[str, Any],
    chunks: int,
    compatibility_mode: str,
) -> dict[str, Any]:
    ttft = None if first_output is None else max(first_output - started, 0.0)
    e2e = max(ended - started, 0.0)
    completion_tokens = _number(usage.get("completion_tokens"))
    prompt_tokens = _number(usage.get("prompt_tokens"))
    if completion_tokens is None:
        completion_tokens = _number(timings.get("predicted_n"))
    if prompt_tokens is None:
        prompt_n = _number(timings.get("prompt_n"))
        cache_n = _number(timings.get("cache_n"))
        if prompt_n is not None:
            prompt_tokens = prompt_n + (cache_n or 0.0)

    decode_s = None
    effective_decode_tps = None
    tpot_s = None
    if ttft is not None and ended >= first_output:
        decode_s = max(ended - first_output, 0.0)
        if completion_tokens is not None and completion_tokens > 1 and decode_s > 0:
            generated_after_first = completion_tokens - 1.0
            effective_decode_tps = generated_after_first / decode_s
            tpot_s = decode_s / generated_after_first

    effective_prefill_tps = None
    if prompt_tokens is not None and ttft is not None and ttft > 0:
        # This is intentionally named "effective": it includes queue/network/client
        # overhead and must not be confused with provider-internal prompt throughput.
        effective_prefill_tps = prompt_tokens / ttft

    provider_ttft = _number(metrics.get("time_to_first_token_ms"))
    provider_ttft = provider_ttft / 1000.0 if provider_ttft is not None else None
    provider_generation = _number(metrics.get("generation_time_ms"))
    provider_generation = provider_generation / 1000.0 if provider_generation is not None else None
    provider_queue = _number(metrics.get("queue_time_ms"))
    provider_queue = provider_queue / 1000.0 if provider_queue is not None else None
    provider_mean_itl = _number(metrics.get("mean_itl_ms"))
    provider_mean_itl = provider_mean_itl / 1000.0 if provider_mean_itl is not None else None

    if provider_ttft is None:
        provider_ttft = _number(meta_info.get("ttft"))
    provider_tpot = _number(meta_info.get("tpot"))
    if provider_mean_itl is None and provider_tpot is not None:
        provider_mean_itl = provider_tpot

    provider_effective_prefill_tps = None
    if prompt_tokens is not None and provider_ttft is not None and provider_ttft > 0:
        provider_effective_prefill_tps = prompt_tokens / provider_ttft
    provider_effective_decode_tps = None
    if (
        completion_tokens is not None
        and completion_tokens > 1
        and provider_generation is not None
        and provider_generation > 0
    ):
        provider_effective_decode_tps = (completion_tokens - 1.0) / provider_generation
    elif completion_tokens is not None and completion_tokens > 1 and provider_tpot is not None and provider_tpot > 0:
        provider_effective_decode_tps = 1.0 / provider_tpot

    return {
        "ok": first_output is not None,
        "compatibility_mode": compatibility_mode,
        "chunks": chunks,
        "client_ttft_s": ttft,
        "e2e_s": e2e,
        "decode_s": decode_s,
        "tpot_s": tpot_s,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "effective_prefill_tps": effective_prefill_tps,
        "effective_decode_tps": effective_decode_tps,
        "server_prefill_tps": _number(timings.get("prompt_per_second")),
        "server_decode_tps": _number(timings.get("predicted_per_second")),
        "provider_ttft_s": provider_ttft,
        "provider_generation_s": provider_generation,
        "provider_queue_s": provider_queue,
        "provider_mean_itl_s": provider_mean_itl,
        "provider_tokens_per_second": _number(metrics.get("tokens_per_second")),
        "provider_effective_prefill_tps": provider_effective_prefill_tps,
        "provider_effective_decode_tps": provider_effective_decode_tps,
    }


async def _stream_one(
    http: httpx.AsyncClient,
    client: ChatClient,
    prompt: str,
    *,
    max_tokens: int,
    timeout_s: float,
) -> dict[str, Any]:
    payload = _policy_payload(client, prompt, max_tokens)
    headers = {"Authorization": f"Bearer {client.api_key}", "Content-Type": "application/json"}

    async def attempt(body: dict[str, Any], compatibility_mode: str) -> dict[str, Any]:
        started = time.perf_counter()
        first_output = None
        usage: dict[str, Any] = {}
        timings: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        meta_info: dict[str, Any] = {}
        chunks = 0
        async with asyncio.timeout(timeout_s):
            async with http.stream(
                "POST",
                client.base_url + "/chat/completions",
                json=body,
                headers=headers,
                timeout=timeout_s,
            ) as response:
                if response.status_code >= 400:
                    # Speed probes may perform one compatibility fallback for servers
                    # that stream but do not implement stream_options.include_usage.
                    if response.status_code in {400, 422} and "stream_options" in body:
                        raise _StreamOptionsUnsupported()
                    response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or line.startswith(":") or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    chunks += 1
                    content = _content_from_chunk(chunk)
                    if content and first_output is None:
                        first_output = time.perf_counter()
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    if isinstance(chunk.get("timings"), dict):
                        timings = chunk["timings"]
                    if isinstance(chunk.get("metrics"), dict):
                        metrics = chunk["metrics"]
                    if isinstance(chunk.get("meta_info"), dict):
                        meta_info = chunk["meta_info"]
        ended = time.perf_counter()
        return _sample_from_stream(
            started=started,
            first_output=first_output,
            ended=ended,
            usage=usage,
            timings=timings,
            metrics=metrics,
            meta_info=meta_info,
            chunks=chunks,
            compatibility_mode=compatibility_mode,
        )

    try:
        return await attempt(payload, "stream+usage")
    except _StreamOptionsUnsupported:
        fallback = dict(payload)
        fallback.pop("stream_options", None)
        return await attempt(fallback, "stream-no-usage")


class _StreamOptionsUnsupported(Exception):
    pass


def _summarize(samples: list[dict[str, Any]], *, elapsed_s: float, concurrency: int) -> dict[str, Any]:
    successes = [sample for sample in samples if sample.get("ok")]
    prompt_tokens = sum(sample["prompt_tokens"] for sample in successes if sample.get("prompt_tokens") is not None)
    completion_tokens = sum(sample["completion_tokens"] for sample in successes if sample.get("completion_tokens") is not None)
    token_counted = sum(1 for sample in successes if sample.get("completion_tokens") is not None)
    aggregate_output_tps = completion_tokens / elapsed_s if elapsed_s > 0 and token_counted else None

    fields = {
        "client_ttft_s": "ttft",
        "e2e_s": "e2e",
        "tpot_s": "tpot",
        "effective_prefill_tps": "effective_prefill_tps",
        "effective_decode_tps": "effective_decode_tps",
        "server_prefill_tps": "server_prefill_tps",
        "server_decode_tps": "server_decode_tps",
        "provider_ttft_s": "provider_ttft",
        "provider_queue_s": "provider_queue",
        "provider_mean_itl_s": "provider_mean_itl",
        "provider_generation_s": "provider_generation",
        "provider_tokens_per_second": "provider_tokens_per_second",
        "provider_effective_prefill_tps": "provider_effective_prefill_tps",
        "provider_effective_decode_tps": "provider_effective_decode_tps",
    }
    distributions = {
        output: _distribution([sample[field] for sample in successes if sample.get(field) is not None])
        for field, output in fields.items()
    }
    return {
        "concurrency": concurrency,
        "requested": len(samples),
        "succeeded": len(successes),
        "failed": len(samples) - len(successes),
        "success_rate": (len(successes) / len(samples)) if samples else 0.0,
        "elapsed_s": elapsed_s,
        "request_rps": (len(successes) / elapsed_s) if elapsed_s > 0 else None,
        "prompt_tokens": prompt_tokens if successes else None,
        "completion_tokens": completion_tokens if token_counted else None,
        "token_counted_requests": token_counted,
        "aggregate_output_tps": aggregate_output_tps,
        **distributions,
        "samples": samples,
    }


async def _run_level_async(
    client: ChatClient,
    *,
    concurrency: int,
    requests: int,
    prompt_words: int,
    max_tokens: int,
    deadline: float,
    probe_id: str,
    phase: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    timeout_s = deadline - time.monotonic()
    if timeout_s <= 0:
        raise TimeoutError("speed probe deadline reached")
    limits = httpx.Limits(max_connections=max(16, concurrency * 2), max_keepalive_connections=max(8, concurrency))
    async with httpx.AsyncClient(limits=limits, follow_redirects=False) as http:
        semaphore = asyncio.Semaphore(concurrency)

        async def run(index: int) -> dict[str, Any]:
            async with semaphore:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"ok": False, "error_type": "DeadlineExceeded"}
                prompt = synthetic_prompt(
                    concurrency=concurrency,
                    index=index,
                    words=prompt_words,
                    probe_id=probe_id,
                    phase=phase,
                )
                try:
                    return await _stream_one(
                        http,
                        client,
                        prompt,
                        max_tokens=max_tokens,
                        timeout_s=min(client.timeout, remaining),
                    )
                except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException):
                    return {"ok": False, "error_type": "TimeoutError"}
                except httpx.HTTPStatusError as exc:
                    return {"ok": False, "error_type": f"HTTP{exc.response.status_code}"}
                except httpx.HTTPError:
                    return {"ok": False, "error_type": "HTTPError"}
                except Exception as exc:  # keep speed diagnostics non-secret
                    return {"ok": False, "error_type": type(exc).__name__}

        samples = await asyncio.gather(*(run(index) for index in range(requests)))
    elapsed = time.perf_counter() - started
    return _summarize(samples, elapsed_s=elapsed, concurrency=concurrency)


def run_level(
    client: ChatClient,
    *,
    concurrency: int,
    requests: int,
    prompt_words: int,
    max_tokens: int,
    deadline: float,
    probe_id: str | None = None,
    phase: str = "measure",
) -> dict[str, Any]:
    return asyncio.run(
        _run_level_async(
            client,
            concurrency=concurrency,
            requests=requests,
            prompt_words=prompt_words,
            max_tokens=max_tokens,
            deadline=deadline,
            probe_id=probe_id or uuid.uuid4().hex[:12],
            phase=phase,
        )
    )


def recommend_concurrency(levels: list[dict[str, Any]], *, knee_fraction: float = 0.90) -> dict[str, Any]:
    valid = [level for level in levels if level.get("succeeded", 0) >= 1 and level.get("success_rate", 0) >= 0.95]
    if not valid:
        raise ValueError("no concurrency level completed with at least 95% request success")

    metric_name = "aggregate_output_tps"
    metric_values = [level.get(metric_name) for level in valid]
    if not any(isinstance(value, (int, float)) and value > 0 for value in metric_values):
        metric_name = "request_rps"

    ranked = [
        (float(level[metric_name]), int(level["concurrency"]), level)
        for level in valid
        if isinstance(level.get(metric_name), (int, float)) and level[metric_name] > 0
    ]
    if not ranked:
        raise ValueError("speed probes completed but exposed no usable throughput metric")

    peak_value, peak_concurrency, _ = max(ranked, key=lambda item: (item[0], -item[1]))
    threshold = peak_value * knee_fraction
    recommended = min((item for item in ranked if item[0] >= threshold), key=lambda item: item[1])
    recommended_value, recommended_concurrency, _ = recommended

    confidence = "high"
    if metric_name == "request_rps" or len(valid) < 3:
        confidence = "medium"
    if sum(level.get("succeeded", 0) for level in valid) < 12:
        confidence = "low"

    return {
        "method": CURVE_METHOD,
        "selection_metric": metric_name,
        "knee_fraction": knee_fraction,
        "peak_concurrency": peak_concurrency,
        "peak_value": peak_value,
        "recommended_concurrency": recommended_concurrency,
        "recommended_value": recommended_value,
        "recommended_fraction_of_peak": recommended_value / peak_value if peak_value else None,
        "confidence": confidence,
        "reason": (
            f"smallest concurrency reaching at least {knee_fraction:.0%} of measured peak "
            f"{metric_name}; lower concurrency wins near-ties to reduce latency and KV pressure"
        ),
    }


def discover_concurrency(
    client: ChatClient,
    *,
    candidates: str | list[int] | tuple[int, ...] = DEFAULT_CANDIDATES,
    max_seconds: float = DEFAULT_CURVE_SECONDS,
    prompt_words: int = DEFAULT_PROMPT_WORDS,
    max_tokens: int = 64,
    requests_per_worker: int = 2,
    min_requests: int = 4,
    knee_fraction: float = 0.90,
    outer_deadline: float | None = None,
) -> dict[str, Any]:
    candidates = parse_candidates(candidates)
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("curve max_seconds must be finite and positive")
    if not 0.5 <= knee_fraction <= 1.0:
        raise ValueError("knee fraction must be between 0.5 and 1.0")
    if requests_per_worker < 1 or min_requests < 1:
        raise ValueError("curve request counts must be positive")

    started = time.monotonic()
    deadline = started + max_seconds
    if outer_deadline is not None:
        deadline = min(deadline, outer_deadline)

    probe_id = uuid.uuid4().hex[:12]
    warmup = None
    if time.monotonic() < deadline:
        warmup = run_level(
            client,
            concurrency=1,
            requests=1,
            prompt_words=max(32, min(prompt_words, 128)),
            max_tokens=max(2, min(max_tokens, 16)),
            deadline=deadline,
            probe_id=probe_id,
            phase="warmup",
        )

    levels: list[dict[str, Any]] = []
    for concurrency in candidates:
        if time.monotonic() >= deadline:
            break
        requests = max(min_requests, concurrency * requests_per_worker)
        level = run_level(
            client,
            concurrency=concurrency,
            requests=requests,
            prompt_words=prompt_words,
            max_tokens=max_tokens,
            deadline=deadline,
            probe_id=probe_id,
            phase=f"curve-c{concurrency}",
        )
        levels.append(level)

    recommendation = recommend_concurrency(levels, knee_fraction=knee_fraction)
    return {
        "schema": "sixcat-concurrency-curve-v1",
        "unscored": True,
        "synthetic_prompts": True,
        "prompt_words": prompt_words,
        "max_tokens": max_tokens,
        "candidate_concurrency": candidates,
        "measured_levels": [level["concurrency"] for level in levels],
        "duration_s": time.monotonic() - started,
        "deadline_s": max_seconds,
        "probe_id": probe_id,
        "warmup": warmup,
        "levels": levels,
        **recommendation,
    }


def confirmation_run(
    client: ChatClient,
    *,
    concurrency: int,
    samples: int,
    prompt_words: int,
    max_tokens: int,
    deadline: float,
) -> dict[str, Any]:
    if samples < 1:
        raise ValueError("speed confirmation samples must be positive")
    probe_id = uuid.uuid4().hex[:12]
    warmup = run_level(
        client,
        concurrency=1,
        requests=1,
        prompt_words=max(32, min(prompt_words, 128)),
        max_tokens=max(2, min(max_tokens, 16)),
        deadline=deadline,
        probe_id=probe_id,
        phase="warmup",
    )
    result = run_level(
        client,
        concurrency=concurrency,
        requests=samples,
        prompt_words=prompt_words,
        max_tokens=max_tokens,
        deadline=deadline,
        probe_id=probe_id,
        phase="confirmation",
    )
    result["warmup"] = warmup
    result["probe_id"] = probe_id
    result["p99_sample_warning"] = result["succeeded"] < 100
    result["p99_note"] = (
        "p99 is an interpolated empirical percentile with fewer than 100 successful requests; "
        "use --samples 100 or more for a more meaningful tail estimate"
        if samples < 100
        else None
    )
    return result


def render_curve(curve: dict[str, Any]) -> str:
    lines = [
        "CONCURRENCY CURVE (unscored synthetic probes)",
        f"{'C':>4} {'ok':>7} {'out t/s':>10} {'req/s':>9} {'TTFT p95':>10} {'E2E p95':>10} {'dec p50':>10}",
        "-" * 72,
    ]
    for level in curve.get("levels") or []:
        ttft = (level.get("ttft") or {}).get("p95")
        e2e = (level.get("e2e") or {}).get("p95")
        decode = (level.get("effective_decode_tps") or {}).get("p50")
        lines.append(
            f"{level['concurrency']:>4} "
            f"{level['succeeded']}/{level['requested']:<5} "
            f"{_fmt(level.get('aggregate_output_tps')):>10} "
            f"{_fmt(level.get('request_rps')):>9} "
            f"{_fmt_ms(ttft):>10} "
            f"{_fmt_ms(e2e):>10} "
            f"{_fmt(decode):>10}"
        )
    lines.extend(
        [
            "-" * 72,
            f"recommended concurrency: {curve.get('recommended_concurrency')} "
            f"(peak={curve.get('peak_concurrency')}, confidence={curve.get('confidence')})",
            f"selection: {curve.get('reason')}",
        ]
    )
    return "\n".join(lines)


def render_confirmation(result: dict[str, Any]) -> str:
    lines = [
        "",
        f"SPEED CONFIRMATION @ concurrency={result['concurrency']} "
        f"({result['succeeded']}/{result['requested']} successful)",
        f"aggregate output throughput: {_fmt(result.get('aggregate_output_tps'))} tok/s",
        f"request rate: {_fmt(result.get('request_rps'))} req/s",
        f"client TTFT: p50={_fmt_ms((result['ttft']).get('p50'))} "
        f"p95={_fmt_ms((result['ttft']).get('p95'))} "
        f"p99={_fmt_ms((result['ttft']).get('p99'))}",
        f"E2E latency: p50={_fmt_ms((result['e2e']).get('p50'))} "
        f"p95={_fmt_ms((result['e2e']).get('p95'))} "
        f"p99={_fmt_ms((result['e2e']).get('p99'))}",
        f"TPOT: p50={_fmt_ms((result['tpot']).get('p50'))} "
        f"p95={_fmt_ms((result['tpot']).get('p95'))} "
        f"p99={_fmt_ms((result['tpot']).get('p99'))}",
        f"effective prefill: p5={_fmt((result['effective_prefill_tps']).get('p5'))} "
        f"p50={_fmt((result['effective_prefill_tps']).get('p50'))} tok/s "
        "(client-observed; includes queue/network)",
        f"effective decode: p5={_fmt((result['effective_decode_tps']).get('p5'))} "
        f"p50={_fmt((result['effective_decode_tps']).get('p50'))} tok/s",
        f"server prefill: p5={_fmt((result['server_prefill_tps']).get('p5'))} "
        f"p50={_fmt((result['server_prefill_tps']).get('p50'))} tok/s",
        f"server decode: p5={_fmt((result['server_decode_tps']).get('p5'))} "
        f"p50={_fmt((result['server_decode_tps']).get('p50'))} tok/s",
    ]
    provider_ttft = (result.get("provider_ttft") or {}).get("p50")
    if provider_ttft is not None:
        lines.append(f"provider TTFT p50: {_fmt_ms(provider_ttft)}")
    provider_queue = (result.get("provider_queue") or {}).get("p50")
    if provider_queue is not None:
        lines.append(f"provider queue p50: {_fmt_ms(provider_queue)}")
    provider_prefill = (result.get("provider_effective_prefill_tps") or {}).get("p50")
    if provider_prefill is not None:
        lines.append(f"provider-effective prefill p50: {_fmt(provider_prefill)} tok/s")
    provider_decode = (result.get("provider_effective_decode_tps") or {}).get("p50")
    if provider_decode is not None:
        lines.append(f"provider-effective decode p50: {_fmt(provider_decode)} tok/s")
    if result.get("p99_sample_warning"):
        lines.append("NOTE: p99 has <100 request samples; use --samples 100+ for stronger tail-latency evidence.")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    return "n/a" if not isinstance(value, (int, float)) else f"{float(value):.2f}"


def _fmt_ms(value: Any) -> str:
    return "n/a" if not isinstance(value, (int, float)) else f"{float(value) * 1000.0:.1f}ms"


def _resolve_cli_policy(args) -> Any:
    if args.policy == "custom":
        if args.temperature is None:
            raise ValueError("--policy custom requires --temperature")
        policy = custom_policy(
            temperature=args.temperature,
            top_p=args.top_p,
            top_k=args.top_k,
            min_p=args.min_p,
            thinking=args.thinking == "on",
            seed=args.seed,
        )
    else:
        policy = resolve_policy(
            args.policy,
            args.model,
            seed=args.seed,
            family=args.policy_family if args.policy == "vendor" else None,
        )
    if args.thinking is not None:
        policy = override_thinking(policy, args.thinking == "on")
    return policy


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sixcat speed",
        description="Measure serving speed/latency and optionally discover the concurrency throughput knee.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8085/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default=os.environ.get("SIXCAT_API_KEY", "none"))
    parser.add_argument("--policy", choices=("strict", "vendor", "custom"), default="strict")
    parser.add_argument("--policy-family", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--min-p", type=float, default=None)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--thinking", choices=("on", "off"), default="off")
    parser.add_argument("--concurrency", type=int, default=None, help="Skip curve discovery and confirm this fixed concurrency.")
    parser.add_argument("--candidates", default="1,2,4,8")
    parser.add_argument("--curve-seconds", type=float, default=60.0)
    parser.add_argument("--curve-requests-per-worker", type=int, default=2)
    parser.add_argument("--curve-min-requests", type=int, default=4)
    parser.add_argument("--knee-fraction", type=float, default=0.90)
    parser.add_argument("--samples", type=int, default=DEFAULT_CONFIRM_SAMPLES)
    parser.add_argument("--prompt-words", type=int, default=DEFAULT_PROMPT_WORDS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--max-seconds", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.concurrency is not None and args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    for name in ("curve_seconds", "max_seconds", "request_timeout"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be finite and positive")
    if args.samples < 1 or args.prompt_words < 16 or args.max_tokens < 2:
        parser.error("--samples must be >=1, --prompt-words >=16, and --max-tokens >=2")
    if not 0.5 <= args.knee_fraction <= 1.0:
        parser.error("--knee-fraction must be between 0.5 and 1.0")

    custom_values = (args.temperature, args.top_p, args.top_k, args.min_p)
    if args.policy == "custom" and args.temperature is None:
        parser.error("--policy custom requires --temperature")
    if args.policy != "custom" and any(value is not None for value in custom_values):
        parser.error("--temperature/--top-p/--top-k/--min-p require --policy custom")
    if args.policy_family and args.policy != "vendor":
        parser.error("--policy-family requires --policy vendor")
    try:
        policy = _resolve_cli_policy(args)
        candidates = parse_candidates(args.candidates) if args.concurrency is None else [args.concurrency]
    except ValueError as exc:
        parser.error(str(exc))

    client = ChatClient(
        args.base_url,
        args.model,
        policy,
        api_key=args.api_key,
        timeout=args.request_timeout,
    )
    server_props = fetch_server_props(args.base_url, args.api_key)
    total = TimeBudget(args.max_seconds)
    curve = None
    if args.concurrency is None:
        curve = discover_concurrency(
            client,
            candidates=candidates,
            max_seconds=min(args.curve_seconds, total.remaining() or args.curve_seconds),
            prompt_words=args.prompt_words,
            max_tokens=min(args.max_tokens, 64),
            requests_per_worker=args.curve_requests_per_worker,
            min_requests=args.curve_min_requests,
            knee_fraction=args.knee_fraction,
            outer_deadline=total.deadline,
        )
        selected = int(curve["recommended_concurrency"])
        print(render_curve(curve))
    else:
        selected = args.concurrency

    if total.expired():
        parser.error("speed curve consumed the total speed-test budget before confirmation")
    confirmation = confirmation_run(
        client,
        concurrency=selected,
        samples=args.samples,
        prompt_words=args.prompt_words,
        max_tokens=args.max_tokens,
        deadline=total.deadline,
    )
    print(render_confirmation(confirmation))
    report = {
        "schema": SPEED_SCHEMA,
        "unscored": True,
        "model": args.model,
        "base_url": args.base_url.rstrip("/"),
        "policy": policy.to_dict(),
        "policy_fingerprint": policy.fingerprint,
        "server_props": server_props,
        "curve": curve,
        "selected_concurrency": selected,
        "confirmation": confirmation,
        "total_elapsed_s": time.monotonic() - total.start,
    }
    if args.out:
        atomic_write_json(args.out, report)
        print(f"\nwrote {args.out}")
    return 0 if confirmation["succeeded"] == confirmation["requested"] else 2
