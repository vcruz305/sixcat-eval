from __future__ import annotations

import math
from typing import Any

CACHE_TTL_S = 60.0
MAX_PLAUSIBLE_CTX = 10_485_760
ETA_P50_OUTPUT = 500
ETA_P95_OUTPUT = 2000
TIMEOUT_SLACK_S = 120.0
UNRELIABLE_TPS_FLOOR = 5.0
MIN_RELIABLE_COMPLETION_TOKENS = 64
THINK_ON_RECOMMENDED_CTX = 32768
THINK_ON_MINIMUM_CTX = 8192
SAFETY_ABS = 512
SAFETY_FRAC = 0.02

CTX_UNKNOWN = "CTX_UNKNOWN"
CTX_CONFLICT = "CTX_CONFLICT"
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
MODEL_AMBIGUOUS = "MODEL_AMBIGUOUS"
CTX_INVALID_VALUE = "CTX_INVALID_VALUE"
USAGE_UNAVAILABLE = "USAGE_UNAVAILABLE"
ETA_LOW_CONFIDENCE = "ETA_LOW_CONFIDENCE"
PROBE_TIMEOUT = "PROBE_TIMEOUT"
CASE_EXCEEDS_CONTEXT = "CASE_EXCEEDS_CONTEXT"
CTX_STALE_CACHE = "CTX_STALE_CACHE"
CTX_TIGHT = "CTX_TIGHT"
CTX_TOO_SMALL = "CTX_TOO_SMALL"
CTX_ENDPOINT_UNAVAILABLE = "CTX_ENDPOINT_UNAVAILABLE"
CTX_FIELD_ABSENT = "CTX_FIELD_ABSENT"

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_preflight_cache() -> None:
    _CACHE.clear()


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def parse_ctx_value(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            return None
        parsed = int(text)
    else:
        return None
    if parsed < 1 or parsed > MAX_PLAUSIBLE_CTX:
        return None
    return parsed


def safety_margin(ctx_advertised: int) -> int:
    return max(SAFETY_ABS, math.ceil(ctx_advertised * SAFETY_FRAC))


def derive_input_budget(ctx_advertised: int | None, output_reserve: int) -> dict[str, int | None]:
    if ctx_advertised is None:
        return {"safety_margin": None, "input_budget": None, "output_reserve": output_reserve}
    margin = safety_margin(ctx_advertised)
    return {
        "safety_margin": margin,
        "output_reserve": output_reserve,
        "input_budget": max(0, ctx_advertised - output_reserve - margin),
    }


def evaluate_prompt_fit(*, prompt_tokens: int, ctx_advertised: int, output_reserve: int) -> dict[str, Any]:
    derived = derive_input_budget(ctx_advertised, output_reserve)
    input_budget = int(derived["input_budget"] or 0)
    fits_advertised = prompt_tokens + output_reserve <= ctx_advertised
    fits_input_budget = prompt_tokens <= input_budget
    warning_code = None
    if fits_advertised and not fits_input_budget:
        warning_code = CASE_EXCEEDS_CONTEXT
    elif not fits_advertised:
        warning_code = CASE_EXCEEDS_CONTEXT
    return {
        "fits_advertised": fits_advertised,
        "fits_input_budget": fits_input_budget,
        "input_budget": input_budget,
        "safety_margin": derived["safety_margin"],
        "warning_code": warning_code,
    }


def _model_basename(model_id: str) -> str:
    return model_id.rsplit("/", 1)[-1].strip().casefold()


def match_models(requested: str, available: list[str]) -> dict[str, Any]:
    if not requested or not isinstance(requested, str):
        return {"status": "missing", "matches": [], "rule": None, "resolved_model": None}
    ids = [item for item in available if isinstance(item, str) and item]
    exact = [item for item in ids if item == requested]
    if len(exact) == 1:
        return {"status": "exact", "matches": exact, "rule": "exact", "resolved_model": exact[0]}
    if len(exact) > 1:
        return {"status": "ambiguous", "matches": exact, "rule": "exact", "resolved_model": None}
    casefold = [item for item in ids if item.casefold() == requested.casefold()]
    if len(casefold) == 1:
        return {"status": "alias", "matches": casefold, "rule": "casefold", "resolved_model": casefold[0]}
    if len(casefold) > 1:
        return {"status": "ambiguous", "matches": casefold, "rule": "casefold", "resolved_model": None}
    base = [item for item in ids if _model_basename(item) == _model_basename(requested)]
    if len(base) == 1:
        return {"status": "alias", "matches": base, "rule": "basename", "resolved_model": base[0]}
    if len(base) > 1:
        return {"status": "ambiguous", "matches": base, "rule": "basename", "resolved_model": None}
    return {"status": "missing", "matches": [], "rule": None, "resolved_model": None}


def _candidate(
    *,
    value: int,
    source: str,
    field_path: str,
    layer: str,
    model_id: str | None,
    raw: Any,
) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "field_path": field_path,
        "layer": layer,
        "model_id": model_id,
        "raw": raw,
    }


def collect_llama_cpp_candidates(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    specs = [
        ("n_ctx", payload.get("n_ctx"), "runtime_total_ctx"),
        (
            "default_generation_settings.n_ctx",
            (payload.get("default_generation_settings") or {}).get("n_ctx")
            if isinstance(payload.get("default_generation_settings"), dict)
            else None,
            "runtime_total_ctx",
        ),
        ("max_position_embeddings", payload.get("max_position_embeddings"), "native_max_ctx"),
    ]
    out: list[dict[str, Any]] = []
    for field_path, raw, layer in specs:
        parsed = parse_ctx_value(raw)
        if parsed is None:
            continue
        out.append(
            _candidate(
                value=parsed,
                source="llama_cpp_props",
                field_path=field_path,
                layer=layer,
                model_id=None,
                raw=raw,
            )
        )
    return out


def collect_openai_model_candidates(
    payload: dict[str, Any] | None, requested_model: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(payload, dict):
        return [], {"status": "absent", "matches": [], "rule": None, "resolved_model": None}
    available: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id:
                available.append(model_id)
                by_id[model_id] = item
    match = match_models(requested_model, available)
    if match["status"] in {"missing", "ambiguous"}:
        return [], match
    resolved = match["resolved_model"]
    row = by_id.get(resolved) or {}
    specs = [
        ("max_model_len", row.get("max_model_len"), "runtime_total_ctx"),
        ("context_length", row.get("context_length"), "runtime_total_ctx"),
        ("max_position_embeddings", row.get("max_position_embeddings"), "native_max_ctx"),
        ("max_sequence_length", row.get("max_sequence_length"), "native_max_ctx"),
    ]
    candidates: list[dict[str, Any]] = []
    for field, raw, layer in specs:
        parsed = parse_ctx_value(raw)
        if parsed is None:
            continue
        candidates.append(
            _candidate(
                value=parsed,
                source="openai_models",
                field_path=f"data[id={resolved}].{field}",
                layer=layer,
                model_id=resolved,
                raw=raw,
            )
        )
    return candidates, match


def _source_label(candidate: dict[str, Any]) -> str:
    source = candidate.get("source")
    field = candidate.get("field_path") or ""
    if source == "configured":
        return "configured"
    if source == "llama_cpp_props":
        return f"/props {field}"
    if source == "openai_models":
        return f"/v1/models {field}"
    return f"{source} {field}".strip()


def resolve_context(
    candidates: list[dict[str, Any]],
    *,
    requested_model: str,
    configured_ctx: int | None = None,
    model_match_status: str = "exact",
    resolved_model: str | None = None,
    invalid_values: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []
    recorded = [dict(item) for item in candidates]
    configured_candidate = None
    if configured_ctx is not None:
        parsed = parse_ctx_value(configured_ctx)
        if parsed is None:
            warnings.append(_warning(CTX_INVALID_VALUE, f"configured context {configured_ctx!r} is not a usable token count"))
        else:
            configured_candidate = _candidate(
                value=parsed,
                source="configured",
                field_path="configured_ctx",
                layer="configured",
                model_id=requested_model,
                raw=configured_ctx,
            )
            recorded = [configured_candidate, *recorded]

    if configured_candidate is not None:
        return {
            "requested_model": requested_model,
            "resolved_model": resolved_model,
            "ctx_advertised": configured_candidate["value"],
            "ctx_source": "configured",
            "ctx_candidates": recorded,
            "ctx_confidence": "high",
            "warnings": warnings,
        }

    if model_match_status == "ambiguous":
        warnings.append(_warning(MODEL_AMBIGUOUS, "multiple server models matched the requested ID; context is unknown"))
        return {
            "requested_model": requested_model,
            "resolved_model": None,
            "ctx_advertised": None,
            "ctx_source": None,
            "ctx_candidates": recorded,
            "ctx_confidence": "unknown",
            "warnings": warnings,
        }
    if model_match_status == "missing":
        warnings.append(_warning(MODEL_NOT_FOUND, f"requested model {requested_model!r} was not in /v1/models"))

    if invalid_values:
        warnings.append(_warning(CTX_INVALID_VALUE, "one or more context fields were non-numeric, zero, negative, or implausible"))

    usable = [
        item
        for item in candidates
        if item.get("model_id") in (None, resolved_model) or resolved_model is None and item.get("model_id") is None
    ]
    if model_match_status == "ambiguous":
        usable = []

    layer_order = ("runtime_total_ctx", "default_request_ctx", "native_max_ctx")
    chosen_layer = next((layer for layer in layer_order if any(item.get("layer") == layer for item in usable)), None)
    layer_items = [item for item in usable if item.get("layer") == chosen_layer] if chosen_layer else []
    if not layer_items:
        warnings.append(_warning(CTX_UNKNOWN, "no usable context metadata for the requested model"))
        return {
            "requested_model": requested_model,
            "resolved_model": resolved_model,
            "ctx_advertised": None,
            "ctx_source": None,
            "ctx_candidates": recorded,
            "ctx_confidence": "unknown",
            "warnings": warnings,
        }

    values = sorted({int(item["value"]) for item in layer_items})
    selected_value = values[0]
    if len(values) > 1:
        warnings.append(
            _warning(
                CTX_CONFLICT,
                f"runtime context candidates disagree {values}; using the smaller value {selected_value}",
            )
        )
    selected = next(item for item in layer_items if int(item["value"]) == selected_value)
    if chosen_layer == "native_max_ctx":
        confidence = "low"
    elif len(values) > 1 or model_match_status == "alias":
        confidence = "medium"
    elif model_match_status in {"exact", "server"}:
        confidence = "high"
    else:
        confidence = "medium"
    return {
        "requested_model": requested_model,
        "resolved_model": resolved_model,
        "ctx_advertised": selected_value,
        "ctx_source": _source_label(selected),
        "ctx_candidates": recorded,
        "ctx_confidence": confidence,
        "warnings": warnings,
    }


def _is_timeout_reason(reason: Any) -> bool:
    text = str(reason or "").casefold()
    return "timed out" in text or "timeout" in text or "timed_out" in text


def _optional_nonneg_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


def account_probe_usage(probe: dict[str, Any] | None) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []
    probe = probe if isinstance(probe, dict) else {}
    if _is_timeout_reason(probe.get("reason")) or str(probe.get("status") or "").casefold() == "timeout":
        warnings.append(_warning(PROBE_TIMEOUT, "active probe timed out; ETA is unavailable"))
    prompt = _optional_nonneg_number(probe.get("prompt_tokens"))
    completion = _optional_nonneg_number(probe.get("completion_tokens"))
    reasoning = _optional_nonneg_number(probe.get("reasoning_tokens"))
    wall_s = _optional_nonneg_number(probe.get("wall_s"))
    prefill_tps = _optional_nonneg_number(probe.get("prefill_tps"))
    decode_tps = _optional_nonneg_number(probe.get("decode_tps"))
    wall_tps = _optional_nonneg_number(probe.get("wall_tps"))
    if wall_tps is None and completion is not None and wall_s and wall_s > 0:
        wall_tps = completion / wall_s
    if prompt is not None or completion is not None or reasoning is not None:
        usage_source = "api_usage"
    else:
        usage_source = "unavailable"
        if probe:
            warnings.append(_warning(USAGE_UNAVAILABLE, "probe did not report token usage; do not assume 256 tokens"))
    finish = probe.get("finish")
    tps_reliable = (
        finish == "stop"
        and completion is not None
        and completion >= MIN_RELIABLE_COMPLETION_TOKENS
        and (decode_tps is not None or wall_tps is not None)
    )
    return {
        "usage_source": usage_source,
        "prompt_tokens": None if prompt is None else int(prompt),
        "completion_tokens": None if completion is None else int(completion),
        "reasoning_tokens": None if reasoning is None else int(reasoning),
        "wall_s": wall_s,
        "prefill_tps": prefill_tps,
        "decode_tps": decode_tps,
        "wall_tps": wall_tps,
        "finish": finish,
        "tps_reliable": tps_reliable,
        "warnings": warnings,
    }


def estimate_run_eta(*, n_items: int, probe_account: dict[str, Any]) -> dict[str, Any]:
    warnings = list(probe_account.get("warnings") or [])
    prefill_tps = probe_account.get("prefill_tps")
    decode_tps = probe_account.get("decode_tps") or probe_account.get("wall_tps")
    prompt_n = probe_account.get("prompt_tokens")
    reasoning = probe_account.get("reasoning_tokens")
    if not decode_tps or decode_tps <= 0 or n_items <= 0:
        warnings.append(_warning(ETA_LOW_CONFIDENCE, "not enough measured decode rate for an ETA range"))
        return {
            "eta_low_s": None,
            "eta_high_s": None,
            "confidence": "unknown",
            "n_items": n_items,
            "warnings": warnings,
        }
    prefill_low = (float(prompt_n) / float(prefill_tps)) if prompt_n and prefill_tps and prefill_tps > 0 else 0.0
    extra_reason = float(reasoning or 0)
    low_out = float(ETA_P50_OUTPUT) + extra_reason
    high_out = float(ETA_P95_OUTPUT) + extra_reason
    if reasoning is None:
        high_out *= 1.5
        warnings.append(_warning(ETA_LOW_CONFIDENCE, "hidden reasoning tokens were not reported; ETA is a range"))
    item_low = prefill_low + (low_out / float(decode_tps))
    item_high = prefill_low + (high_out / float(decode_tps))
    if probe_account.get("tps_reliable") and reasoning is not None:
        confidence = "high"
    elif probe_account.get("tps_reliable"):
        confidence = "medium"
    else:
        confidence = "low"
        warnings.append(_warning(ETA_LOW_CONFIDENCE, "probe TPS is unreliable (short, truncated, or cold)"))
    return {
        "eta_low_s": float(n_items) * item_low,
        "eta_high_s": float(n_items) * item_high,
        "confidence": confidence,
        "n_items": n_items,
        "decode_tps": decode_tps,
        "prefill_tps": prefill_tps,
        "warnings": warnings,
    }


def suggest_request_timeout_s(ctx_advertised: int | None, probe_account: dict[str, Any]) -> float | None:
    if ctx_advertised is None:
        return None
    rate = probe_account.get("decode_tps") or probe_account.get("wall_tps")
    if not rate or rate <= 0:
        if probe_account.get("tps_reliable"):
            return None
        rate = UNRELIABLE_TPS_FLOOR
    return float(ctx_advertised) / float(rate) + TIMEOUT_SLACK_S


def _split_server_props(server_props: dict[str, Any] | None) -> tuple[Any, Any, Any, Any, str | None]:
    if not isinstance(server_props, dict):
        return None, None, None, None, None
    source = server_props.get("source")
    props = server_props.get("props")
    llama = server_props.get("llama_cpp_props")
    openai = server_props.get("openai_models")
    if llama is None and source == "llama_cpp_props" and isinstance(props, dict):
        llama = props
    if openai is None and source == "openai_models" and isinstance(props, dict):
        openai = props
    return llama, openai, server_props.get("props_error"), server_props.get("models_error"), source if isinstance(source, str) else None


def _minutes_range(low_s: float | None, high_s: float | None) -> str | None:
    if low_s is None or high_s is None:
        return None
    low_m = max(1, int(round(low_s / 60.0))) if low_s >= 30 else max(1, int(math.ceil(low_s / 60.0)))
    high_m = max(low_m, int(round(high_s / 60.0)))
    if low_s < 60 and high_s < 90:
        return f"{int(round(low_s))}-{int(round(high_s))} seconds"
    return f"{low_m}-{high_m} minutes"


def format_preflight(preflight: dict[str, Any]) -> str:
    ctx = preflight.get("ctx_advertised")
    ctx_cell = f"{ctx:,} tokens" if isinstance(ctx, int) else "unknown"
    reserve = preflight.get("output_reserve")
    margin = preflight.get("safety_margin")
    budget = preflight.get("input_budget")
    eta = _minutes_range(preflight.get("eta_low_s"), preflight.get("eta_high_s"))
    confidence = preflight.get("eta_confidence") or preflight.get("ctx_confidence") or "unknown"
    eta_cell = f"{eta} ({confidence} confidence)" if eta else f"unavailable ({confidence} confidence)"
    lines = [
        "Preflight",
        f"  model: {preflight.get('resolved_model') or preflight.get('requested_model')}",
        f"  served context: {ctx_cell}",
        f"  source: {preflight.get('ctx_source') or 'unavailable'}",
        f"  output reserve: {reserve:,} tokens" if isinstance(reserve, int) else "  output reserve: unknown",
        f"  safety margin: {margin:,} tokens" if isinstance(margin, int) else "  safety margin: n/a",
        f"  safe input budget: {budget:,} tokens" if isinstance(budget, int) else "  safe input budget: unknown",
        f"  ETA: {eta_cell}",
    ]
    for item in preflight.get("warnings") or []:
        lines.append(f"  warning: {item.get('code')}: {item.get('message')}")
    return "\n".join(lines)


def assemble_preflight(
    *,
    requested_model: str,
    server_props: dict[str, Any] | None,
    probe: dict[str, Any] | None,
    n_items: int,
    output_reserve: int,
    configured_ctx: int | None = None,
    thinking: bool = False,
    cache_key: str | None = None,
    cached: dict[str, Any] | None = None,
    store_cache: bool = False,
    use_cache: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    import time as time_module

    clock = time_module.monotonic() if now is None else now
    llama, openai, props_error, models_error, source = _split_server_props(server_props)
    llama_candidates = collect_llama_cpp_candidates(llama if isinstance(llama, dict) else None)
    openai_candidates, match = collect_openai_model_candidates(
        openai if isinstance(openai, dict) else None, requested_model
    )
    if openai is None and llama_candidates:
        match = {"status": "server", "matches": [], "rule": None, "resolved_model": None}

    invalid_values: list[dict[str, Any]] = []
    if isinstance(llama, dict):
        for field, raw in (
            ("n_ctx", llama.get("n_ctx")),
            (
                "default_generation_settings.n_ctx",
                (llama.get("default_generation_settings") or {}).get("n_ctx")
                if isinstance(llama.get("default_generation_settings"), dict)
                else None,
            ),
        ):
            if raw is not None and parse_ctx_value(raw) is None:
                invalid_values.append({"field_path": field, "raw": raw})

    resolved = resolve_context(
        [*llama_candidates, *openai_candidates],
        requested_model=requested_model,
        configured_ctx=configured_ctx,
        model_match_status=match["status"],
        resolved_model=match.get("resolved_model"),
        invalid_values=invalid_values,
    )
    warnings = list(resolved["warnings"])
    if source == "unavailable":
        warnings.append(_warning(CTX_ENDPOINT_UNAVAILABLE, "context metadata endpoints were unavailable"))
        if resolved["ctx_advertised"] is None and CTX_UNKNOWN not in {item["code"] for item in warnings}:
            warnings.append(_warning(CTX_UNKNOWN, "no usable context metadata for the requested model"))
    if isinstance(openai, dict) and match["status"] == "missing" and not llama_candidates:
        if CTX_UNKNOWN not in {item["code"] for item in warnings}:
            warnings.append(_warning(CTX_UNKNOWN, "no usable context metadata for the requested model"))
    if llama is None and openai is None and source not in {None, "unavailable"}:
        warnings.append(_warning(CTX_FIELD_ABSENT, "server identity was present but context fields were absent"))

    cached_payload = cached
    if use_cache and cache_key and cached_payload is None:
        hit = _CACHE.get(cache_key)
        if hit is not None:
            ts, payload = hit
            if clock - ts <= CACHE_TTL_S:
                cached_payload = payload
    if cached_payload and resolved["ctx_advertised"] is not None:
        previous = cached_payload.get("ctx_advertised")
        if previous is not None and previous != resolved["ctx_advertised"]:
            warnings.append(
                _warning(
                    CTX_STALE_CACHE,
                    f"cached context {previous} lost to fresh metadata {resolved['ctx_advertised']}",
                )
            )
    elif use_cache and cache_key and resolved["ctx_advertised"] is None:
        # Expired or missing cache must not resurrect a stale advertised context.
        pass

    derived = derive_input_budget(resolved["ctx_advertised"], output_reserve)
    account = account_probe_usage(probe)
    eta = estimate_run_eta(n_items=n_items, probe_account=account)
    warnings.extend(account["warnings"])
    for item in eta["warnings"]:
        if item not in warnings:
            warnings.append(item)

    advertised = resolved["ctx_advertised"]
    if thinking and isinstance(advertised, int):
        if advertised < THINK_ON_MINIMUM_CTX:
            warnings.append(_warning(CTX_TOO_SMALL, f"served context {advertised} is below 8192; long think-on items may ctx-fail"))
        elif advertised < THINK_ON_RECOMMENDED_CTX:
            warnings.append(_warning(CTX_TIGHT, f"served context {advertised} is below 32768; long think-on traces may ctx-fail"))

    timeout = suggest_request_timeout_s(advertised, account)
    result = {
        "phase": "observe",
        "requested_model": requested_model,
        "resolved_model": resolved["resolved_model"],
        "ctx_advertised": advertised,
        "ctx_source": resolved["ctx_source"],
        "ctx_candidates": resolved["ctx_candidates"],
        "ctx_confidence": resolved["ctx_confidence"],
        "output_reserve": output_reserve,
        "safety_margin": derived["safety_margin"],
        "input_budget": derived["input_budget"],
        "usage_source": account["usage_source"],
        "eta_low_s": eta["eta_low_s"],
        "eta_high_s": eta["eta_high_s"],
        "eta_confidence": eta["confidence"],
        "suggested_request_timeout_s": timeout,
        "probe_account": {key: value for key, value in account.items() if key != "warnings"},
        "warnings": warnings,
    }
    if store_cache and cache_key:
        _CACHE[cache_key] = (clock, dict(result))
    return result
