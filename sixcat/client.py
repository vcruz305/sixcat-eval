from __future__ import annotations

import json
import copy
import queue
import threading
from .http_transport import open_request
from .runtime import effective_timeout
from .score import _strip_reasoning
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from .policy import Policy


def _root_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root


def _optional_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _empty_speed() -> dict[str, Any]:
    return {
        "prefill_n": None,
        "decode_n": None,
        "prefill_ms": None,
        "decode_ms": None,
        "prefill_tps": None,
        "decode_tps": None,
        "speed_source": None,
    }


def extract_server_timings(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy provider speed fields when present. Never invent a prefill/decode split."""
    out = _empty_speed()
    if not isinstance(payload, dict):
        return out
    timings = payload.get("timings")
    if isinstance(timings, dict) and any(
        timings.get(key) is not None
        for key in ("prompt_per_second", "predicted_per_second", "prompt_ms", "predicted_ms")
    ):
        out.update(
            {
                "prefill_n": _optional_number(timings.get("prompt_n")),
                "decode_n": _optional_number(timings.get("predicted_n")),
                "prefill_ms": _optional_number(timings.get("prompt_ms")),
                "decode_ms": _optional_number(timings.get("predicted_ms")),
                "prefill_tps": _optional_number(timings.get("prompt_per_second")),
                "decode_tps": _optional_number(timings.get("predicted_per_second")),
                "speed_source": "llama_cpp_timings",
            }
        )
        return out
    meta = payload.get("meta_info")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    if isinstance(meta, dict):
        ttft = _optional_number(meta.get("ttft"))
        tpot = _optional_number(meta.get("tpot"))
        prompt_n = _optional_number(usage.get("prompt_tokens"))
        if ttft and ttft > 0 and prompt_n:
            out["prefill_tps"] = float(prompt_n) / float(ttft)
            out["prefill_n"] = prompt_n
            out["prefill_ms"] = float(ttft) * 1000.0
        if tpot and tpot > 0:
            out["decode_tps"] = 1.0 / float(tpot)
            decode_n = _optional_number(usage.get("completion_tokens"))
            out["decode_n"] = decode_n
            if decode_n:
                out["decode_ms"] = float(decode_n) * float(tpot) * 1000.0
        if out["prefill_tps"] is not None or out["decode_tps"] is not None:
            out["speed_source"] = "sglang_meta"
    return out


def _reasoning_from_message(msg: dict[str, Any], data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Normalize provider reasoning text and hidden-trace metadata."""
    raw_reason = msg.get("reasoning_content")
    if raw_reason in (None, ""):
        raw_reason = msg.get("reasoning")
    if isinstance(raw_reason, dict):
        text = str(raw_reason.get("content") or raw_reason.get("text") or "")
    else:
        text = str(raw_reason or "")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    token_details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
    if not isinstance(token_details, dict):
        token_details = {}
    reasoning_tokens = None
    for candidate in (
        usage.get("reasoning_tokens"),
        token_details.get("reasoning_tokens"),
        token_details.get("reasoning"),
    ):
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)) or candidate < 0:
            continue
        reasoning_tokens = int(candidate)
        break
    return text, {
        "reasoning_tokens": reasoning_tokens,
        "reasoning_details": msg.get("reasoning_details") or data.get("reasoning_details"),
        "thinking_field": msg.get("thinking"),
    }


def apply_stream_speed(
    timings: dict[str, Any],
    *,
    prompt_n: float | int | None,
    decode_n: float | int | None,
    ttft_s: float | None,
    wall_s: float | None,
) -> dict[str, Any]:
    """Fill a prefill/decode split from stream TTFT only when the server omitted one."""
    out = dict(timings)
    if out.get("prefill_tps") is not None and out.get("decode_tps") is not None:
        return out
    if not ttft_s or ttft_s <= 0 or not wall_s or wall_s <= ttft_s:
        return out
    if prompt_n:
        out["prefill_n"] = prompt_n
        out["prefill_ms"] = float(ttft_s) * 1000.0
        out["prefill_tps"] = float(prompt_n) / float(ttft_s)
    if decode_n is not None:
        # First completion token arrives at TTFT; remaining tokens are decode.
        decode_after_first = max(float(decode_n) - 1.0, 0.0)
        decode_s = float(wall_s) - float(ttft_s)
        out["decode_n"] = decode_n
        out["decode_ms"] = decode_s * 1000.0
        out["decode_tps"] = decode_after_first / decode_s if decode_s > 0 else None
    out["speed_source"] = "stream_ttft"
    return out


def _get_json(url: str, headers: dict[str, str], timeout: float) -> tuple[Any, str | None]:
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with open_request(req, timeout=effective_timeout(timeout)) as resp:
            return json.loads(resp.read().decode()), None
    except Exception as exc:
        return None, str(exc)


def fetch_server_props(base_url: str, api_key: str = "none", timeout: float = 10.0) -> dict[str, Any]:
    """Best-effort server identity fingerprint, for run provenance (Phase 1).

    Queries llama.cpp `/props` and OpenAI-compatible `/v1/models` independently.
    Never raises; a probe that can't identify the server is itself a fact worth recording.
    `source`/`props` keep the historical primary payload; extra keys hold both raw bodies.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    root = _root_url(base_url)
    llama_cpp_props, props_error = _get_json(root + "/props", headers, timeout)
    openai_models, models_error = _get_json(base_url.rstrip("/") + "/models", headers, timeout)
    if llama_cpp_props is not None:
        source = "llama_cpp_props"
        primary = llama_cpp_props
    elif openai_models is not None:
        source = "openai_models"
        primary = openai_models
    else:
        return {
            "source": "unavailable",
            "error": models_error or props_error,
            "llama_cpp_props": None,
            "openai_models": None,
            "props_error": props_error,
            "models_error": models_error,
        }
    return {
        "source": source,
        "props": primary,
        "llama_cpp_props": llama_cpp_props,
        "openai_models": openai_models,
        "props_error": props_error,
        "models_error": models_error,
    }


class ChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        policy: Policy,
        api_key: str = "none",
        timeout: float = 180.0,
        transport: str = "openai",
        stdio_in=None,
        stdio_out=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.policy = policy
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport or "openai"
        self.stdio_in = stdio_in
        self.stdio_out = stdio_out
        self._stdio_lock = threading.Lock()
        self._stdio_poisoned = False

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        request_params: dict[str, Any] = {
            "temperature": self.policy.temperature,
            "max_tokens": max_tokens,
            "enable_thinking": self.policy.thinking,
        }
        for key in ("top_p", "top_k", "min_p"):
            value = getattr(self.policy, key)
            if value is not None:
                request_params[key] = value
        request_params.update(self.policy.extra)
        template_kwargs: dict[str, Any] = {"enable_thinking": self.policy.thinking}
        if request_params.pop("preclose_think", False):
            template_kwargs["enable_thinking"] = False
        effort = self.policy.extra.get("reasoning_effort")
        if effort is not None:
            template_kwargs["reasoning_effort"] = effort
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            **{key: value for key, value in request_params.items() if key != "enable_thinking"},
            "chat_template_kwargs": template_kwargs,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        # Keep wire settings as well as requested policy settings: template overrides
        # such as preclose_think must be visible in receipts, not silently inferred.
        wire_request = copy.deepcopy(payload)
        if self.transport == "stdio":
            with self._stdio_lock:
                result = self._complete_stdio(payload, request_params)
            result["wire_request"] = wire_request
            return result
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with open_request(req, timeout=effective_timeout(self.timeout)) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: completion request rejected") from e
        wall_s = time.perf_counter() - started
        if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or not data["choices"]:
            raise ValueError("completion response requires a non-empty choices array")
        choice = data["choices"][0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("completion response requires a message object")
        msg = choice["message"]
        if msg.get("content") is not None and not isinstance(msg["content"], str):
            raise ValueError("completion content must be text or null")
        if msg.get("tool_calls") is not None and not isinstance(msg["tool_calls"], list):
            raise ValueError("tool_calls must be an array")
        usage = data.get("usage") or {}
        timings = extract_server_timings(data)
        completion_tokens = usage.get("completion_tokens")
        wall_tps = None
        if (
            isinstance(completion_tokens, (int, float))
            and not isinstance(completion_tokens, bool)
            and wall_s > 0
        ):
            wall_tps = float(completion_tokens) / wall_s
        # Reasoning traces are not standardized: DeepSeek/Qwen use
        # `reasoning_content`, OpenAI/Together use `reasoning`, and some
        # cloud gateways hide the text while still reporting token counts.
        reasoning, reasoning_meta = _reasoning_from_message(msg, data)
        return {
            "text": _strip_reasoning(msg.get("content") or ""),
            "source_text": msg.get("content") or "",
            "wire_request": wire_request,
            "provider_model": data.get("model"),
            "system_fingerprint": data.get("system_fingerprint"),
            "tool_calls": msg.get("tool_calls") or [],
            "finish": choice.get("finish_reason"),
            "reasoning_content": reasoning,
            "reasoning_tokens": reasoning_meta["reasoning_tokens"],
            "reasoning_details": reasoning_meta["reasoning_details"],
            "thinking_field": reasoning_meta["thinking_field"],
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": completion_tokens,
                "reasoning_tokens": reasoning_meta["reasoning_tokens"],
                "completion_tokens_details": usage.get("completion_tokens_details"),
            },
            **timings,
            "wall_s": wall_s,
            "wall_tps": wall_tps,
            "request_params": request_params,
            "raw": data,
        }

    def _complete_stdio(self, payload: dict[str, Any], request_params: dict[str, Any]) -> dict[str, Any]:
        """Ask a harness for one completion. Protocol JSONL on stdio; never log secrets."""
        req_id = uuid.uuid4().hex
        messages = payload.get("messages") or []
        prompt = ""
        if messages:
            prompt = str(messages[0].get("content") or "")
        msg = {
            "op": "complete",
            "id": req_id,
            "model": self.model,
            "prompt": prompt,
            "max_tokens": payload.get("max_tokens"),
            "tools": payload.get("tools"),
            "request_params": dict(request_params),
            "wire_request": copy.deepcopy(payload),
        }
        out = self.stdio_out if self.stdio_out is not None else sys.stdout
        inp = self.stdio_in if self.stdio_in is not None else sys.stdin
        started = time.perf_counter()
        if self._stdio_poisoned:
            raise RuntimeError("stdio transport is desynchronized after a timeout; start a fresh harness")
        response_timeout = effective_timeout(self.timeout)
        reply = queue.Queue(maxsize=1)
        def exchange():
            try:
                out.write(json.dumps(msg, ensure_ascii=False) + "\n")
                out.flush()
                line = inp.readline(16 * 1024 * 1024 + 1)
                reply.put((line, None))
            except Exception as exc:
                reply.put((None, exc))
        threading.Thread(target=exchange, name="sixcat-stdio", daemon=True).start()
        try:
            line, error = reply.get(timeout=response_timeout)
        except (queue.Empty, TimeoutError) as exc:
            self._stdio_poisoned = True
            raise TimeoutError("stdio response deadline reached; harness must be restarted") from exc
        if error is not None:
            self._stdio_poisoned = True
            raise error
        if len(line) > 16 * 1024 * 1024:
            self._stdio_poisoned = True
            raise ValueError("stdio response exceeds 16 MiB safety limit")
        if not line:
            self._stdio_poisoned = True
            raise RuntimeError("stdio transport: harness closed stdin before answering")
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            self._stdio_poisoned = True
            raise RuntimeError("stdio transport: harness sent non-JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("stdio transport: harness answer must be a JSON object")
        if data.get("id") not in (None, req_id):
            self._stdio_poisoned = True
            raise RuntimeError(f"stdio transport: id mismatch {data.get('id')!r} != {req_id}")
        wall_s = time.perf_counter() - started
        text = data.get("text")
        if text is None:
            text = data.get("content") or ""
        text = text if isinstance(text, str) else str(text)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        completion_tokens = usage.get("completion_tokens")
        wall_tps = None
        if (
            isinstance(completion_tokens, (int, float))
            and not isinstance(completion_tokens, bool)
            and wall_s > 0
        ):
            wall_tps = float(completion_tokens) / wall_s
        fake_msg = {
            "content": text,
            "reasoning_content": data.get("reasoning_content") or "",
            "tool_calls": data.get("tool_calls") or [],
        }
        reasoning, reasoning_meta = _reasoning_from_message(fake_msg, data)
        return {
            "text": _strip_reasoning(text),
            "source_text": text,
            "wire_request": copy.deepcopy(payload),
            "provider_model": data.get("model"),
            "system_fingerprint": data.get("system_fingerprint"),
            "tool_calls": fake_msg["tool_calls"],
            "finish": data.get("finish") or data.get("finish_reason"),
            "reasoning_content": reasoning,
            "reasoning_tokens": reasoning_meta["reasoning_tokens"],
            "reasoning_details": reasoning_meta["reasoning_details"],
            "thinking_field": reasoning_meta["thinking_field"],
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": completion_tokens,
                "reasoning_tokens": reasoning_meta["reasoning_tokens"],
                "completion_tokens_details": usage.get("completion_tokens_details"),
            },
            **extract_server_timings(data),
            "wall_s": wall_s,
            "wall_tps": wall_tps,
            "request_params": request_params,
            "raw": data,
        }
