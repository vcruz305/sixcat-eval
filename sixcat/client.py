from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
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


def fetch_server_props(base_url: str, api_key: str = "none", timeout: float = 10.0) -> dict[str, Any]:
    """Best-effort server identity fingerprint, for run provenance (Phase 1).

    Tries llama.cpp's `/props` first (model path, build info, n_ctx), then falls back to
    the OpenAI-compatible `/v1/models` (vLLM/SGLang/llama.cpp all serve this). Never raises;
    a probe that can't identify the server is itself a fact worth recording.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    root = _root_url(base_url)
    try:
        req = urllib.request.Request(root + "/props", headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return {"source": "llama_cpp_props", "props": data}
    except Exception:
        pass
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/models", headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return {"source": "openai_models", "props": data}
    except Exception as e:
        return {"source": "unavailable", "error": str(e)}


class ChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        policy: Policy,
        api_key: str = "none",
        timeout: float = 180.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.policy = policy
        self.api_key = api_key
        self.timeout = timeout

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
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            **{key: value for key, value in request_params.items() if key != "enable_thinking"},
            "chat_template_kwargs": {"enable_thinking": self.policy.thinking},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
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
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"HTTP {e.code}: {body[:400]}") from e
        wall_s = time.perf_counter() - started
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
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
        return {
            "text": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
            "finish": choice.get("finish_reason"),
            "reasoning_content": msg.get("reasoning_content") or "",
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": completion_tokens,
            },
            **timings,
            "wall_s": wall_s,
            "wall_tps": wall_tps,
            "request_params": request_params,
            "raw": data,
        }
