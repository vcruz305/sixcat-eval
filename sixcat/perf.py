"""Unscored serving-speed probes and concurrency curve discovery.

The speed path deliberately uses synthetic prompts that begin with unique markers,
so it does not pre-warm SixCat's scored questions or create a large shared prefix.
Client-observed TTFT includes network + queue + prefill. Provider/server metrics are
kept separately when the OpenAI-compatible endpoint exposes them.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import statistics
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from .client import ChatClient, fetch_server_props
from .journal import TimeBudget
from .policy import custom_policy, override_thinking, resolve_policy
from .storage import atomic_write_json
from .speed_stream import _content_from_chunk, _policy_payload, _sample_from_stream, _stream_one

SPEED_SCHEMA = "sixcat-speed-v3"
CURVE_METHOD = "smallest-concurrency-within-90pct-peak-v1"
DEFAULT_CANDIDATES = (1, 2, 4, 8)
DEFAULT_CURVE_SECONDS = 60.0
DEFAULT_CONFIRM_SAMPLES = 32
DEFAULT_QUICK_SAMPLES = 5
PROMPT_DATASET = "sixcat-speed-prose-code-v1"
DEFAULT_SPEED_PROFILES = ("decode", "balanced", "prefill")
WORKLOAD_PROFILES: dict[str, dict[str, Any]] = {
    "quick": {
        "prompt_words": 512,
        "max_tokens": 256,
        "purpose": "short single-user TTFT, effective prefill and generation check",
    },
    "decode": {
        "prompt_words": 32,
        "max_tokens": 512,
        "purpose": "short prompt + long generation to expose sustained decode speed",
    },
    "balanced": {
        "prompt_words": 256,
        "max_tokens": 128,
        "purpose": "mixed prompt/generation workload for realistic serving throughput",
    },
    "prefill": {
        "prompt_words": 2048,
        "max_tokens": 32,
        "purpose": "long prompt + short generation to expose prompt-ingestion speed",
    },
}

# Backward-compatible library defaults map to the Balanced workload.
DEFAULT_PROMPT_WORDS = int(WORKLOAD_PROFILES["balanced"]["prompt_words"])
DEFAULT_MAX_TOKENS = int(WORKLOAD_PROFILES["balanced"]["max_tokens"])


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
        return {"n": 0, "min": None, "p5": None, "p50": None, "p90": None, "p95": None, "p99": None, "max": None, "mean": None}
    return {
        "n": len(clean),
        "min": min(clean),
        "p5": _percentile(clean, 0.05),
        "p50": _percentile(clean, 0.50),
        "p90": _percentile(clean, 0.90),
        "p95": _percentile(clean, 0.95),
        "p99": _percentile(clean, 0.99),
        "max": max(clean),
        "mean": statistics.fmean(clean),
    }


def resolve_workloads(
    profile: str,
    *,
    prompt_words: int | None = None,
    max_tokens: int | None = None,
) -> list[dict[str, Any]]:
    if profile == "all":
        return [{"name": name, **WORKLOAD_PROFILES[name]} for name in DEFAULT_SPEED_PROFILES]
    if profile == "custom":
        if prompt_words is None or max_tokens is None:
            raise ValueError("--profile custom requires --prompt-words and --max-tokens")
        return [{
            "name": "custom",
            "prompt_words": prompt_words,
            "max_tokens": max_tokens,
            "purpose": "operator-defined custom serving workload",
        }]
    if profile not in WORKLOAD_PROFILES:
        raise ValueError(f"unknown speed profile {profile!r}")
    workload = {"name": profile, **WORKLOAD_PROFILES[profile]}
    if prompt_words is not None:
        workload["prompt_words"] = prompt_words
    if max_tokens is not None:
        workload["max_tokens"] = max_tokens
    return [workload]


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


def synthetic_prompt(*, concurrency: int, index: int, words: int, probe_id: str, phase: str) -> str:
    """Frozen synthetic prose/code tasks; unique early markers limit prefix reuse."""
    marker = f"SIXCAT-SPEED-{probe_id}-{phase}-C{concurrency}-I{index}"
    passages = (
        "A research observatory collects sensor readings at several remote stations. "
        "Each station stores a timestamp, a measurement and a device identifier. "
        "The team wants to tolerate intermittent connectivity while detecting stale "
        "readings and preserving the original measurement order. Operators review "
        "a daily report that explains missing data, delayed delivery and unusual "
        "measurements. The system must remain understandable to the small team "
        "that maintains it, including people who did not write the original software.",

        "A library is reorganizing its public workshop schedule. Some visitors can "
        "attend only on weekends, while others prefer short evening sessions. "
        "The available rooms have different capacities and equipment. Instructors "
        "need preparation time between sessions. The organizer wants a practical "
        "plan that balances availability, accessibility and maintenance effort. "
        "A good proposal states its assumptions, identifies tradeoffs and suggests "
        "a small first experiment that can be evaluated before expanding the program.",

        "An engineering team maintains a service that accepts events from independent "
        "clients. Clients occasionally retry an event after a timeout, and their "
        "clocks are not perfectly synchronized. A request can succeed even if its "
        "acknowledgment is lost. The service should make duplicate handling explicit "
        "and preserve enough information to investigate mistakes. Monitoring should "
        "help distinguish a slow dependency from a busy queue or a failed operation. "
        "Changes will be rolled out gradually with a documented recovery procedure.",

        "Consider this pseudocode: create an empty dictionary named latest; for each "
        "record, read its device key; compare its timestamp with the timestamp stored "
        "for that key; replace the stored record only when the new timestamp is later; "
        "return the dictionary values sorted by device key. Records can arrive out "
        "of order and two records can have the same timestamp. The implementation "
        "needs a stated tie-breaking rule and a clear policy for missing fields."
    )
    tasks = (
        "Explain a practical design for the observatory data pipeline, including its failure cases.",
        "Propose a workshop scheduling plan and explain the tradeoffs behind your choices.",
        "Explain how to implement safe event retries and how to verify the resulting behavior.",
        "Write a Python implementation of the pseudocode and explain its edge cases.",
        "Compare two implementation approaches for the described systems and justify a recommendation."
    )
    pool = " ".join(passages[(index + offset) % len(passages)] for offset in range(len(passages))).split()
    body = " ".join(pool[pos % len(pool)] for pos in range(words))
    return (
        f"[{marker}] This is an unscored synthetic serving-performance task. "
        "Read the supplied context and give a detailed, self-contained response to "
        "the task. Use the model's configured reasoning mode.\n\n"
        f"Context:\n{body}\n\nTask: {tasks[index % len(tasks)]}"
    )

def _summarize(samples: list[dict[str, Any]], *, elapsed_s: float, concurrency: int) -> dict[str, Any]:
    successes = [sample for sample in samples if sample.get("ok")]
    token_counted = sum(sample.get("completion_tokens") is not None for sample in successes)
    prompt_counted = sum(sample.get("prompt_tokens") is not None for sample in successes)
    known_completion = sum(sample["completion_tokens"] for sample in successes if sample.get("completion_tokens") is not None)
    known_prompt = sum(sample["prompt_tokens"] for sample in successes if sample.get("prompt_tokens") is not None)
    full_output_coverage = bool(successes) and token_counted == len(successes)
    aggregate_output_tps = known_completion / elapsed_s if elapsed_s > 0 and full_output_coverage else None
    fields = {
        "client_ttft_s": "ttft",
        "client_ttfo_s": "ttfo",
        "e2e_s": "e2e",
        "stream_end_s": "stream_end",
        "tpot_s": "tpot",
        "prompt_tokens": "prompt_token_lengths",
        "completion_tokens": "completion_token_lengths",
        "reasoning_tokens": "reasoning_token_lengths",
        "answer_tokens": "answer_token_lengths",
        "cached_prompt_tokens": "cached_prompt_token_lengths",
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
    observations = {
        field: dict(sorted(Counter(str(sample.get(field) or "unavailable") for sample in successes).items()))
        for field in ("reasoning_observation", "decode_metric_status", "prefill_metric_status", "ttfo_metric_status", "token_count_source")
    }
    return {
        "concurrency": concurrency,
        "requested": len(samples),
        "succeeded": len(successes),
        "failed": len(samples) - len(successes),
        "success_rate": len(successes) / len(samples) if samples else 0.0,
        "elapsed_s": elapsed_s,
        "request_rps": len(successes) / elapsed_s if elapsed_s > 0 else None,
        "prompt_tokens": known_prompt if successes and prompt_counted == len(successes) else None,
        "completion_tokens": known_completion if full_output_coverage else None,
        "known_completion_tokens": known_completion,
        "token_counted_requests": token_counted,
        "token_count_coverage": token_counted / len(successes) if successes else 0.0,
        "aggregate_output_tps": aggregate_output_tps,
        "aggregate_output_tps_status": "complete-token-coverage" if full_output_coverage else "unavailable-incomplete-token-coverage",
        "output_limit_requests": sum(bool(sample.get("output_limit_reached")) for sample in successes),
        "answer_started_requests": sum(sample.get("client_ttfo_s") is not None for sample in successes),
        "finish_reasons": dict(Counter(str(sample.get("finish_reason") or "unspecified") for sample in successes)),
        "observations": observations,
        "tail_sample_warning": len(successes) < 100,
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
    warmup_requests: int = 0,
) -> dict[str, Any]:
    if deadline <= time.monotonic():
        raise TimeoutError("speed probe deadline reached")
    limits = httpx.Limits(max_connections=max(16, concurrency * 2), max_keepalive_connections=max(8, concurrency))
    capabilities = dict(getattr(client, "speed_options", {}) or {})
    async with httpx.AsyncClient(limits=limits, follow_redirects=False) as http:
        async def batch(count: int, batch_concurrency: int, batch_phase: str) -> dict[str, Any]:
            semaphore = asyncio.Semaphore(batch_concurrency)
            started = time.perf_counter()

            async def run(index: int) -> dict[str, Any]:
                async with semaphore:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return {"ok": False, "error_type": "DeadlineExceeded"}
                    prompt = synthetic_prompt(
                        concurrency=batch_concurrency, index=index, words=prompt_words,
                        probe_id=probe_id, phase=batch_phase,
                    )
                    try:
                        return await _stream_one(
                            http, client, prompt, max_tokens=max_tokens,
                            timeout_s=min(client.timeout, remaining), capabilities=capabilities,
                        )
                    except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException):
                        return {"ok": False, "error_type": "TimeoutError"}
                    except httpx.HTTPStatusError as exc:
                        return {"ok": False, "error_type": f"HTTP{exc.response.status_code}"}
                    except httpx.HTTPError:
                        return {"ok": False, "error_type": "HTTPError"}
                    except Exception as exc:
                        return {"ok": False, "error_type": type(exc).__name__}

            samples = await asyncio.gather(*(run(index) for index in range(count)))
            return _summarize(samples, elapsed_s=time.perf_counter() - started, concurrency=batch_concurrency)

        warmup = await batch(warmup_requests, 1, "warmup") if warmup_requests else None
        if warmup is not None and warmup["succeeded"] != warmup["requested"]:
            result = _summarize(
                [{"ok": False, "error_type": "WarmupFailed"} for _ in range(requests)],
                elapsed_s=0.0, concurrency=concurrency,
            )
        else:
            result = await batch(requests, concurrency, phase)
    if warmup is not None:
        result["warmup"] = warmup
        result["warmup_workload"] = {"prompt_words": prompt_words, "max_tokens": max_tokens}
        result["http_client_reused_after_warmup"] = True
    return result

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
    warmup_requests: int = 0,
) -> dict[str, Any]:
    return asyncio.run(
        _run_level_async(
            client, concurrency=concurrency, requests=requests,
            prompt_words=prompt_words, max_tokens=max_tokens, deadline=deadline,
            probe_id=probe_id or uuid.uuid4().hex[:12], phase=phase,
            warmup_requests=warmup_requests,
        )
    )

def recommend_concurrency(
    levels: list[dict[str, Any]],
    *,
    knee_fraction: float = 0.90,
    min_success_rate: float = 0.95,
) -> dict[str, Any]:
    if not 0 < min_success_rate <= 1:
        raise ValueError("minimum success rate must be in (0, 1]")
    for level in levels:
        level["usable"] = bool(
            level.get("succeeded", 0) >= 1
            and level.get("success_rate", 0) >= min_success_rate
        )
    valid = [level for level in levels if level["usable"]]
    if not valid:
        raise ValueError(
            f"no concurrency level completed with at least {min_success_rate:.0%} request success"
        )

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

    max_usable_concurrency = max(int(level["concurrency"]) for level in valid)
    rejected_concurrency = [
        int(level["concurrency"]) for level in levels if not level.get("usable")
    ]
    return {
        "method": CURVE_METHOD,
        "min_success_rate": min_success_rate,
        "max_usable_concurrency": max_usable_concurrency,
        "rejected_concurrency": rejected_concurrency,
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
    min_success_rate: float = 0.95,
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
            prompt_words=prompt_words,
            max_tokens=max_tokens,
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

    diagnostics = {
        "schema": "sixcat-concurrency-curve-v1",
        "unscored": True,
        "synthetic_prompts": True,
        "prompt_dataset": PROMPT_DATASET,
        "prompt_words": prompt_words,
        "max_tokens": max_tokens,
        "candidate_concurrency": candidates,
        "measured_levels": [level["concurrency"] for level in levels],
        "duration_s": time.monotonic() - started,
        "deadline_s": max_seconds,
        "probe_id": probe_id,
        "warmup": warmup,
        "levels": levels,
    }
    try:
        recommendation = recommend_concurrency(
            levels, knee_fraction=knee_fraction, min_success_rate=min_success_rate,
        )
    except ValueError as exc:
        raise ConcurrencyDiscoveryError(diagnostics) from exc
    return {**diagnostics, **recommendation}


class ConcurrencyDiscoveryError(ValueError):
    def __init__(self, curve: dict[str, Any]):
        super().__init__("no usable concurrency level completed within the probe budget")
        self.curve = curve


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
    result = run_level(
        client, concurrency=concurrency, requests=samples,
        prompt_words=prompt_words, max_tokens=max_tokens, deadline=deadline,
        probe_id=probe_id, phase="confirmation", warmup_requests=1,
    )
    result["probe_id"] = probe_id
    result["p99_sample_warning"] = result["succeeded"] < 100
    result["p99_note"] = (
        "Tail percentiles are descriptive empirical estimates with few requests; "
        "use median, range and sample count for quick runs. Even 100 requests is not a p99 service guarantee."
        if result["succeeded"] < 100 else None
    )
    return result

def render_curve(curve: dict[str, Any]) -> str:
    lines = [
        "CONCURRENCY CURVE (unscored synthetic probes)",
        f"{'C':>4} {'ok':>7} {'usable':>7} {'agg t/s':>10} {'req/s':>9} {'TTFT p95':>10} {'dec p50':>10}",
        "-" * 76,
    ]
    for level in curve.get("levels") or []:
        ttft = (level.get("ttft") or {}).get("p95")
        decode = (level.get("effective_decode_tps") or {}).get("p50")
        lines.append(
            f"{level['concurrency']:>4} "
            f"{level['succeeded']}/{level['requested']:<5} "
            f"{('yes' if level.get('usable') else 'NO'):>7} "
            f"{_fmt(level.get('aggregate_output_tps')):>10} "
            f"{_fmt(level.get('request_rps')):>9} "
            f"{_fmt_ms(ttft):>10} "
            f"{_fmt(decode):>10}"
        )
    lines.extend(
        [
            "-" * 76,
            "aggregate output tps = level-wall throughput; includes prefill, queueing, and failure wall time",
            f"max usable concurrency: {curve.get('max_usable_concurrency')} "
            f"(min success={float(curve.get('min_success_rate', 0.95)):.0%})",
            f"recommended concurrency: {curve.get('recommended_concurrency')} "
            f"(usable peak={curve.get('peak_concurrency')}, confidence={curve.get('confidence')})",
            f"selection: {curve.get('reason')}",
        ]
    )
    rejected = curve.get("rejected_concurrency") or []
    if rejected:
        lines.append("excluded from knee for failures: " + ", ".join(f"C={value}" for value in rejected))
    return "\n".join(lines)


def render_confirmation(result: dict[str, Any]) -> str:
    def rate(name: str) -> str:
        dist = result.get(name) or {}
        return (
            f"p50={_fmt(dist.get('p50'))} tok/s "
            f"range={_fmt(dist.get('min'))}..{_fmt(dist.get('max'))} "
            f"n={dist.get('n', 0)}"
        )

    def latency(name: str) -> str:
        dist = result.get(name) or {}
        return (
            f"p50={_fmt_ms(dist.get('p50'))} "
            f"range={_fmt_ms(dist.get('min'))}..{_fmt_ms(dist.get('max'))} "
            f"n={dist.get('n', 0)}"
        )

    lines = [
        "",
        f"SPEED CONFIRMATION @ concurrency={result['concurrency']} "
        f"({result['succeeded']}/{result['requested']} successful)",
        "DECODE: " + rate("effective_decode_tps"),
        "EFFECTIVE PREFILL (client; includes network/queue): " + rate("effective_prefill_tps"),
        "TTFT (first observed generated output): " + latency("ttft"),
        "FIRST ANSWER TOKEN (TTFO): " + latency("ttfo"),
        "E2E (through last generated output): " + latency("e2e"),
        "TPOT: " + latency("tpot"),
        f"aggregate output tps (level wall; includes prefill/queue/failures): {_fmt(result.get('aggregate_output_tps'))} tok/s",
        f"request rate: {_fmt(result.get('request_rps'))} req/s",
        "actual prompt tokens: "
        f"p50={_fmt((result.get('prompt_token_lengths') or {}).get('p50'))}, "
        "actual completion tokens (reasoning + answer): "
        f"p50={_fmt((result.get('completion_token_lengths') or {}).get('p50'))}",
        f"answers started: {result.get('answer_started_requests', 0)}/{result['succeeded']}; "
        f"output cap reached: {result.get('output_limit_requests', 0)}/{result['succeeded']}",
        "native server prefill: " + rate("server_prefill_tps"),
        "native server decode: " + rate("server_decode_tps"),
    ]
    for field, label in (
        ("provider_ttft", "provider TTFT"),
        ("provider_queue", "provider queue"),
    ):
        if (result.get(field) or {}).get("n", 0):
            lines.append(label + ": " + latency(field))
    for field, label in (
        ("provider_effective_prefill_tps", "provider-effective prefill"),
        ("provider_effective_decode_tps", "provider-effective decode"),
    ):
        if (result.get(field) or {}).get("n", 0):
            lines.append(label + ": " + rate(field))
    for field, counts in (result.get("observations") or {}).items():
        if counts:
            lines.append(field.replace("_", " ") + ": " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    if result.get("aggregate_output_tps") is None:
        lines.append("aggregate output TPS unavailable: complete output-token counts are required for every successful request.")
    metric_status = result.get("server_metric_status")
    if isinstance(metric_status, dict) and not metric_status.get("available"):
        lines.append(f"server metrics unavailable for this route: {metric_status.get('reason')}")
    if result.get("tail_sample_warning") or result.get("p99_sample_warning"):
        lines.append("NOTE: use median/range/n for this short run; p95/p99 in JSON are descriptive low-sample estimates.")
    if result.get("output_limit_requests"):
        lines.append("A capped generation is a throughput sample; it does not establish completed-answer latency.")
    return "\n".join(lines)

def server_metric_status(result: dict[str, Any], server_props: dict[str, Any]) -> dict[str, Any]:
    native_fields = (
        "server_prefill_tps",
        "server_decode_tps",
        "provider_ttft",
        "provider_queue",
        "provider_mean_itl",
        "provider_effective_prefill_tps",
        "provider_effective_decode_tps",
    )
    available = [
        name for name in native_fields
        if isinstance(result.get(name), dict) and result[name].get("n", 0) > 0
    ]
    if available:
        return {"available": True, "fields": available, "reason": None}

    props_error = server_props.get("props_error") if isinstance(server_props, dict) else None
    source = server_props.get("source") if isinstance(server_props, dict) else None
    if source == "openai_models" and not server_props.get("llama_cpp_props"):
        reason = "the route exposes /v1/models but no llama.cpp /props and returned no per-request provider timing metrics"
    elif source == "unavailable":
        reason = "server identity/timing endpoints were unavailable and streamed responses returned no native timing metrics"
    elif props_error:
        reason = "native /props timing metadata was unavailable and streamed responses returned no provider timing metrics"
    else:
        reason = "streamed responses did not include native server/provider timing fields"
    return {"available": False, "fields": [], "reason": reason}


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


def _headline_source(profile: dict[str, Any]) -> tuple[dict[str, Any], int | None, str]:
    confirmation = profile.get("confirmation")
    if profile.get("selected_concurrency") == 1 and isinstance(confirmation, dict):
        return confirmation, 1, "confirmation"
    single_stream = profile.get("single_stream_confirmation")
    if isinstance(single_stream, dict):
        return single_stream, 1, "confirmation"
    for level in (profile.get("curve") or {}).get("levels") or []:
        if level.get("concurrency") == 1:
            return level, 1, "discovery-only"
    return confirmation or {}, profile.get("selected_concurrency"), "confirmation"


def _profile_level(profile: dict[str, Any], concurrency: int) -> dict[str, Any] | None:
    source, selected, _ = _headline_source(profile)
    if selected == concurrency:
        return source
    for level in (profile.get("curve") or {}).get("levels") or []:
        if level.get("concurrency") == concurrency:
            return level
    return None

def _summary_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _fmt_copy_tps(value: Any) -> str:
    value = _summary_number(value)
    return "n/a" if value is None else f"{value:,.1f}"


def _fmt_copy_ms(value_s: Any) -> str:
    value_s = _summary_number(value_s)
    return "n/a" if value_s is None else f"{value_s * 1000.0:,.0f}"


def build_speed_summary(profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Headline medians are from confirmed requests, with workload and sample counts."""
    def select(names: tuple[str, ...]) -> tuple[str | None, dict[str, Any]]:
        for name in names:
            if name in profiles:
                return name, profiles[name]
        return None, {}

    decode_name, decode_profile = select(("decode", "quick", "custom", "balanced", "prefill"))
    prefill_name, prefill_profile = select(("prefill", "quick", "custom", "balanced", "decode"))
    latency_name, latency_profile = select(("quick", "balanced", "custom", "decode", "prefill"))
    decode_source, decode_c, decode_phase = _headline_source(decode_profile)
    prefill_source, prefill_c, prefill_phase = _headline_source(prefill_profile)
    latency_source = latency_profile.get("confirmation") or {}
    latency_c = latency_profile.get("selected_concurrency")

    def rate(source: dict[str, Any], field: str, name: str | None, concurrency: int | None, phase: str) -> dict[str, Any]:
        dist = source.get(field) or {}
        return {
            "source_profile": name, "source_concurrency": concurrency, "source_phase": phase,
            "n": dist.get("n", 0),
            "min_tps": _summary_number(dist.get("min")),
            "max_tps": _summary_number(dist.get("max")),
            "p50_tps": _summary_number(dist.get("p50")),
            "p95_tps": _summary_number(dist.get("p95")),
        }

    def latency(field: str) -> dict[str, Any]:
        dist = latency_source.get(field) or {}
        return {
            "profile": latency_name, "concurrency": latency_c, "n": dist.get("n", 0),
            **{
                f"{key}_ms": float(dist[key]) * 1000.0 if _summary_number(dist.get(key)) is not None else None
                for key in ("min", "p50", "p95", "p99", "max")
            },
        }

    capacity_profile = profiles.get("balanced") or latency_profile
    capacity_confirmation = capacity_profile.get("confirmation") or {}
    capacity_curve = capacity_profile.get("curve") or {}
    max_usable = capacity_curve.get("max_usable_concurrency")
    observations = latency_source.get("observations") or {}
    notes = [
        "Client prefill is effective throughput, not isolated engine prefill.",
        "Output counts include reasoning and answer tokens; capped runs do not prove answer completion.",
    ]
    if latency_source.get("tail_sample_warning") or latency_source.get("succeeded", 0) < 100:
        notes.append("Small-sample p95/p99 values are descriptive; use median, range and n.")
    if decode_phase == "discovery-only" or prefill_phase == "discovery-only":
        notes.append("A single-stream headline has discovery-only evidence; no completed C=1 confirmation was available.")
    for field in ("decode_metric_status", "prefill_metric_status", "ttfo_metric_status", "reasoning_observation"):
        counts = observations.get(field) or {}
        if counts:
            notes.append(field.replace("_", " ") + ": " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    balanced = profiles.get("balanced") or {}
    summary = {
        "schema": "sixcat-speed-summary-v2",
        "decode": rate(decode_source, "effective_decode_tps", decode_name, decode_c, decode_phase),
        "prefill": {
            **rate(prefill_source, "effective_prefill_tps", prefill_name, prefill_c, prefill_phase),
            "metric": "client-effective-prefill",
        },
        "ttft": latency("ttft"),
        "ttfo": latency("ttfo"),
        "serving": {
            "profile": "balanced" if profiles.get("balanced") else latency_name,
            "aggregate_output_tps": _summary_number(capacity_confirmation.get("aggregate_output_tps")),
            "concurrency": capacity_profile.get("selected_concurrency"),
        },
        "balanced_serving": {
            "aggregate_output_tps": _summary_number((balanced.get("confirmation") or {}).get("aggregate_output_tps")),
            "concurrency": balanced.get("selected_concurrency"),
        },
        "max_usable_concurrency": max_usable,
        "max_usable_concurrency_evidence": "largest-tested-successful-level" if max_usable is not None else "not-measured",
        "thinking_requested": latency_source.get("thinking_requested"),
        "reasoning_observations": observations.get("reasoning_observation") or {},
        "measurement_notes": notes,
    }
    lines = []
    if decode_name:
        item = summary["decode"]
        lines.append(
            f"**Decode:** {_fmt_copy_tps(item['p50_tps'])} tok/s p50 "
            f"(range {_fmt_copy_tps(item['min_tps'])}–{_fmt_copy_tps(item['max_tps'])}; "
            f"n={item['n']}; C={item['source_concurrency']}; {item['source_profile']})"
        )
    if prefill_name:
        item = summary["prefill"]
        lines.append(
            f"**Effective prefill:** {_fmt_copy_tps(item['p50_tps'])} tok/s p50 "
            f"(n={item['n']}; C={item['source_concurrency']}; {item['source_profile']})"
        )
    if latency_name:
        item = summary["ttft"]
        lines.append(f"**TTFT:** {_fmt_copy_ms((latency_source.get('ttft') or {}).get('p50'))} ms p50 (n={item['n']}; C={latency_c})")
        answer = summary["ttfo"]
        lines.append(f"**First answer (TTFO):** {_fmt_copy_ms((latency_source.get('ttfo') or {}).get('p50'))} ms p50 (n={answer['n']})")
        if summary["thinking_requested"] is not None:
            lines.append("**Thinking requested:** " + ("on" if summary["thinking_requested"] else "off"))
    if max_usable is not None:
        lines.append(f"**Largest tested successful concurrency:** {max_usable}")
    if profiles.get("balanced") or (latency_c is not None and latency_c > 1):
        serving = summary["serving"]
        lines.append(f"**Serving throughput:** {_fmt_copy_tps(serving['aggregate_output_tps'])} tok/s aggregate @ C={serving['concurrency']}")
    summary["copy_paste"] = "\n".join(lines)
    return summary


def render_suite_summary(profiles: dict[str, dict[str, Any]]) -> str:
    summary = build_speed_summary(profiles)
    return "\n".join([
        "", "SIXCAT SPEED — confirmed workload-specific measurements", "-" * 76,
        summary["copy_paste"], "-" * 76, *summary["measurement_notes"],
    ])

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sixcat speed",
        description=(
            "Run a quick thinking-on single-user benchmark by default. "
            "Use --profile all for workload-specific concurrency sweeps."
        ),
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
    parser.add_argument("--thinking", choices=("on", "off"), default="on", help="Requested reasoning mode; default on. Effective behavior is observed separately.")
    parser.add_argument("--reasoning-visibility", choices=("auto", "streamed", "hidden"), default="auto", help="Optional disclosure of provider reasoning visibility; default auto uses stream evidence.")
    parser.add_argument("--per-chunk-usage", action="store_true", help="Request cumulative chunk usage for first-chunk token correction where supported.")
    parser.add_argument(
        "--profile",
        choices=("quick", "all", "decode", "balanced", "prefill", "custom"),
        default="quick",
        help=(
            "Default quick: C=1, 5 measured requests, thinking on, 256 output-token cap. "
            "all runs decode + balanced + prefill with optional capacity tuning."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Skip per-profile curve discovery and confirm this fixed concurrency.",
    )
    parser.add_argument("--auto-concurrency", action="store_true", help="Opt into concurrency discovery for quick; other profiles discover by default unless --concurrency is set.")
    parser.add_argument("--candidates", default="1,2,4,8")
    parser.add_argument("--curve-seconds", type=float, default=120.0)
    parser.add_argument("--curve-requests-per-worker", type=int, default=2)
    parser.add_argument("--curve-min-requests", type=int, default=4)
    parser.add_argument("--knee-fraction", type=float, default=0.90)
    parser.add_argument("--min-success-rate", type=float, default=0.95)
    parser.add_argument("--samples", type=int, default=None, help="Measured requests: default 5 for quick, 32 for other profiles.")
    parser.add_argument(
        "--prompt-words",
        type=int,
        default=None,
        help="Override prompt size for one named profile, or required with --profile custom.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Override the total output-token cap for one named profile, or required with --profile custom.",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="Shared total budget including metadata and warmup; default 120s quick, 600s other profiles.",
    )
    parser.add_argument("--request-timeout", type=float, default=600.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.samples is None:
        args.samples = DEFAULT_QUICK_SAMPLES if args.profile == "quick" else DEFAULT_CONFIRM_SAMPLES
    if args.max_seconds is None:
        args.max_seconds = 120.0 if args.profile == "quick" else 600.0
    if args.auto_concurrency and args.concurrency is not None:
        parser.error("--auto-concurrency cannot be combined with --concurrency")
    use_curve = args.concurrency is None and (args.auto_concurrency or args.profile != "quick")

    if args.concurrency is not None and args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    for name in ("curve_seconds", "max_seconds", "request_timeout"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be finite and positive")
    if args.samples < 1:
        parser.error("--samples must be >= 1")
    if args.prompt_words is not None and args.prompt_words < 16:
        parser.error("--prompt-words must be >= 16")
    if args.max_tokens is not None and args.max_tokens < 2:
        parser.error("--max-tokens must be >= 2")
    if not 0.5 <= args.knee_fraction <= 1.0:
        parser.error("--knee-fraction must be between 0.5 and 1.0")
    if not 0 < args.min_success_rate <= 1.0:
        parser.error("--min-success-rate must be in (0, 1]")
    if args.profile == "all" and (args.prompt_words is not None or args.max_tokens is not None):
        parser.error("--prompt-words/--max-tokens cannot override --profile all; select one profile or custom")

    custom_values = (args.temperature, args.top_p, args.top_k, args.min_p)
    if args.policy == "custom" and args.temperature is None:
        parser.error("--policy custom requires --temperature")
    if args.policy != "custom" and any(value is not None for value in custom_values):
        parser.error("--temperature/--top-p/--top-k/--min-p require --policy custom")
    if args.policy_family and args.policy != "vendor":
        parser.error("--policy-family requires --policy vendor")

    try:
        policy = _resolve_cli_policy(args)
        candidates = parse_candidates(args.candidates) if use_curve else [args.concurrency or 1]
        workloads = resolve_workloads(
            args.profile,
            prompt_words=args.prompt_words,
            max_tokens=args.max_tokens,
        )
    except ValueError as exc:
        parser.error(str(exc))

    client = ChatClient(
        args.base_url, args.model, policy, api_key=args.api_key,
        timeout=args.request_timeout,
    )
    client.speed_options = {
        "per_chunk_usage": args.per_chunk_usage,
        "reasoning_visibility": args.reasoning_visibility,
    }
    total = TimeBudget(args.max_seconds)
    # These two metadata reads share the suite budget as well as generation.
    metadata_timeout = max(0.001, min(3.0, float(total.remaining() or 0.001) / 2.0))
    server_props = fetch_server_props(args.base_url, args.api_key, timeout=metadata_timeout)
    profiles: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    exit_code = 0
    report: dict[str, Any] = {
        "schema": SPEED_SCHEMA,
        "unscored": True,
        "model": args.model,
        "base_url": args.base_url.rstrip("/"),
        "requested_profile": args.profile,
        "requested_profiles": [str(workload["name"]) for workload in workloads],
        "policy": policy.to_dict(),
        "policy_fingerprint": policy.fingerprint,
        "thinking_requested": args.thinking,
        "reasoning_visibility": args.reasoning_visibility,
        "per_chunk_usage_requested": args.per_chunk_usage,
        "prompt_dataset": PROMPT_DATASET,
        "samples_per_confirmation": args.samples,
        "max_seconds": args.max_seconds,
        "server_props": server_props,
        "profiles": profiles,
        "errors": errors,
    }

    def persist(*, final: bool = False) -> None:
        incomplete = [
            name for name in report["requested_profiles"]
            if profiles.get(name, {}).get("status") != "completed"
        ]
        report["status"] = ("incomplete" if incomplete or errors else "completed") if final else "running"
        report["incomplete_profiles"] = incomplete
        report["total_elapsed_s"] = time.monotonic() - total.start
        report["deadline_reached"] = total.expired()
        if len(workloads) == 1 and profiles:
            only = next(iter(profiles.values()))
            for key in ("workload", "curve", "selected_concurrency", "confirmation"):
                report[key] = only.get(key)
        report.pop("summary", None)
        report["summary"] = build_speed_summary(profiles)
        if args.out:
            atomic_write_json(args.out, report)

    print(
        f"SIXCAT SPEED: profile={args.profile} thinking requested={args.thinking} "
        f"sampling={policy.name} samples={args.samples} budget={args.max_seconds:g}s",
        flush=True,
    )
    if args.policy == "vendor" and not policy.source.startswith("vendor:"):
        print("Vendor policy was not matched; the receipt records the strict sampling fallback.", flush=True)
    print("Output caps count reasoning plus answer tokens; actual prompt/completion counts are recorded.", flush=True)
    persist()

    for workload in workloads:
        name = str(workload["name"])
        prompt_words = int(workload["prompt_words"])
        max_tokens = int(workload["max_tokens"])
        profile_result: dict[str, Any] = {
            "workload": {
                "profile": name, "prompt_words": prompt_words,
                "max_tokens": max_tokens, "purpose": workload["purpose"],
                "prompt_length_unit": "body_words",
                "prompt_dataset": PROMPT_DATASET,
                "output_length_policy": "maximum-total-generated-tokens",
            },
            "curve": None,
            "selected_concurrency": args.concurrency or (None if use_curve else 1),
            "status": "running",
            "request_parameters": {
                key: value for key, value in _policy_payload(client, "", max_tokens).items()
                if key != "messages"
            },
        }
        profiles[name] = profile_result
        print(
            f"\n=== {name.upper()} PROFILE ===\n"
            f"workload: prompt_words={prompt_words} max_tokens={max_tokens}\n"
            f"purpose: {workload['purpose']}", flush=True,
        )
        try:
            if total.expired():
                raise TimeoutError("suite deadline reached before profile")
            if use_curve:
                remaining = float(total.remaining() or 0.0)
                curve = discover_concurrency(
                    client, candidates=candidates, max_seconds=min(args.curve_seconds, remaining),
                    prompt_words=prompt_words, max_tokens=max_tokens,
                    requests_per_worker=args.curve_requests_per_worker,
                    min_requests=args.curve_min_requests,
                    knee_fraction=args.knee_fraction, min_success_rate=args.min_success_rate,
                    outer_deadline=total.deadline,
                )
                profile_result["curve"] = curve
                selected = int(curve["recommended_concurrency"])
                profile_result["selected_concurrency"] = selected
                print(render_curve(curve))
            else:
                selected = int(args.concurrency or 1)

            # A C=1 discovery sample is not a substitute for the headline confirmation.
            if use_curve and selected != 1 and name in {"decode", "prefill", "quick"}:
                single = confirmation_run(
                    client, concurrency=1, samples=args.samples,
                    prompt_words=prompt_words, max_tokens=max_tokens, deadline=total.deadline,
                )
                single["thinking_requested"] = policy.thinking
                single["server_metric_status"] = server_metric_status(single, server_props)
                profile_result["single_stream_confirmation"] = single
                print(render_confirmation(single))
                persist()

            if total.expired():
                raise TimeoutError("suite deadline reached before confirmation")
            confirmation = confirmation_run(
                client, concurrency=selected, samples=args.samples,
                prompt_words=prompt_words, max_tokens=max_tokens, deadline=total.deadline,
            )
            confirmation["thinking_requested"] = policy.thinking
            confirmation["server_metric_status"] = server_metric_status(confirmation, server_props)
            profile_result["confirmation"] = confirmation
            profile_result["server_metric_status"] = confirmation["server_metric_status"]
            print(render_confirmation(confirmation))
            checks = [confirmation]
            if "single_stream_confirmation" in profile_result:
                checks.append(profile_result["single_stream_confirmation"])
            complete = all(check["succeeded"] == check["requested"] for check in checks)
            profile_result["status"] = "completed" if complete else "incomplete"
            if not complete:
                exit_code = 2
            persist()
            if total.expired():
                break
        except (ValueError, TimeoutError) as exc:
            if isinstance(exc, ConcurrencyDiscoveryError):
                profile_result["curve"] = exc.curve
            profile_result["status"] = "incomplete"
            profile_result["error_type"] = type(exc).__name__
            errors.append({"profile": name, "error_type": type(exc).__name__})
            exit_code = 2
            print(f"{name}: incomplete ({type(exc).__name__}); retaining collected measurements.", flush=True)
            persist()
            if total.expired():
                break
        except KeyboardInterrupt:
            profile_result["status"] = "incomplete"
            errors.append({"profile": name, "error_type": "KeyboardInterrupt"})
            persist(final=True)
            return 130

    persist(final=True)
    if report["status"] != "completed":
        exit_code = 2
    print(render_suite_summary(profiles))
    if args.out:
        print(f"\nwrote {args.out} ({report['status']})")
    return exit_code
