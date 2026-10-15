"""Public results and generated README tables. Never executes submitted answers."""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import html
import ipaddress
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from .manifest import ATTEMPT_POLICY, fingerprint
from .policy import Policy
from .report import normalise_result
from .score import CATEGORIES

SCHEMA = "sixcat-community-v1"
MAX_BYTES = 10 * 1024 * 1024
START = "<!-- SIXCAT-COMMUNITY:START -->"
END = "<!-- SIXCAT-COMMUNITY:END -->"
REGISTRY = Path(__file__).with_name("community-compatibility.json")
HEX = re.compile(r"[a-f0-9]{64}\Z")
USERNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
META_FIELDS = ("model_name", "model_url", "model_revision", "source_kind", "source",
               "quant_format", "quant_precision", "quant_method", "quant_url", "quant_revision",
               "inference_engine", "engine_version", "api_wrapper", "wrapper_version",
               "evaluation_client", "hardware", "context_tokens", "weight_size_gib", "average_bpw")
RESULT_FIELDS = ("model", "attempt_policy", "benchmark_manifest", "benchmark_fingerprint",
                 "expected_n", "policy", "policy_source", "policy_probe", "policy_fingerprint",
                 "budgets", "parser", "code_execution", "result_schema", "transport", "limit",
                 "limit_scope", "selection_profile", "selection_fingerprint", "timed_out",
                 "categories", "stats", "overall", "overall_label", "overall_flags", "n", "items",
                 "complete", "concurrency", "execution_segments")
ROW_FIELDS = ("cat", "key", "id", "ok", "scored", "status", "attempt", "ts", "segment_id",
              "raw_text", "reasoning_content", "finish", "ctok", "ptok", "rtok", "atok", "loop",
              "parse_confidence", "parse_status", "wall_s", "wall_tps", "provider_model",
              "prefill_tps", "decode_tps", "prefill_ms", "decode_ms", "prefill_n", "decode_n",
              "speed_source", "request_params", "tool_calls", "generation_reused")
SEGMENT_FIELDS = ("id", "concurrency", "elapsed_s", "responses", "token_counted_responses",
                  "completion_tokens", "throughput_tps", "throughput_coverage", "errors", "deadline_reached")
SECRET = re.compile(r"(?:\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b|\bBearer\s+[A-Za-z0-9._~-]{12,}|\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})", re.I)
PRIVATE = re.compile(r"(?:^|\s)(?:/(?:home|Users|root)/\S+|[A-Za-z]:\\Users\\\S+)", re.I)
BANNED_KEYS = {"api_key", "apikey", "authorization", "access_token", "refresh_token", "password",
               "credential", "credentials", "headers", "base_url", "log", "profile", "hermes_profile"}

class SubmissionError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise SubmissionError(message)

def check_tree(value, *, public=False, depth=0):
    require(depth < 32, "JSON nesting exceeds limit")
    if isinstance(value, dict):
        for k, v in value.items():
            require(isinstance(k, str), "JSON keys must be strings")
            if public:
                require(k.casefold() not in BANNED_KEYS, "Unexpected private metadata in public export")
            check_tree(v, public=public, depth=depth + 1)
    elif isinstance(value, list):
        require(len(value) <= 10000, "JSON array exceeds limit")
        for v in value:
            check_tree(v, public=public, depth=depth + 1)
    elif isinstance(value, str):
        require(len(value) <= 1024 * 1024, "JSON text exceeds 1 MiB")
        if public:
            require(not SECRET.search(value), "Possible credential in public text; review locally before upload")
    elif isinstance(value, float):
        require(math.isfinite(value), "Non-finite number")
    else:
        require(value is None or type(value) in (bool, int), "Invalid JSON value")

def strict_json(data):
    require(len(data.encode() if isinstance(data, str) else data) <= MAX_BYTES, "JSON exceeds 10 MiB")
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, "Duplicate JSON key")
            out[k] = v
        return out
    def constant(_):
        raise SubmissionError("Non-finite JSON number")
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
        check_tree(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, SubmissionError):
            raise
        raise SubmissionError("Invalid JSON document") from exc

def read_json(path):
    require(path.is_file() and not path.is_symlink(), "Expected a regular JSON file, not a symlink")
    with path.open("rb") as handle:
        return strict_json(handle.read(MAX_BYTES + 1))

def object_keys(value, allowed, *, required=()):
    require(isinstance(value, dict), "Expected a JSON object")
    require(set(value) <= set(allowed), "Unexpected fields in public document")
    require(set(required) <= set(value), "Missing required public fields")

def load_registry(path=None):
    value = read_json(path or REGISTRY)
    require(value.get("schema") == "sixcat-community-compatibility-v1", "Unsupported compatibility registry")
    return value

def validate_result(result, registry=None):
    """Check saved first verdicts; do not rescore or call any provider."""
    try:
        normalise_result(result)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise SubmissionError("Invalid first-response result") from exc
    require(result.get("complete") is True and result.get("timed_out") is False,
            "Community Results requires a completed, non-timeout run")
    require(result.get("parser") == "v5" and result.get("attempt_policy") == ATTEMPT_POLICY,
            "Only parser-v5 first-response results are accepted")
    require(result.get("limit") == 20 and result.get("limit_scope") == "per_category",
            "Community Results requires the standard 20 items per category")
    require(result.get("n") == result.get("expected_n") == {c: 20 for c in CATEGORIES},
            "All 120 items must be scored, including all 20 Code items")
    require(result.get("code_execution") == "host-guarded", "Code must have been executed locally")
    require(result.get("policy_probe") == "ok", "The policy probe did not pass")
    require(result.get("transport") == "openai", "Agent-assisted stdio results have a different scope")
    require(not result.get("errors"), "Resolve infrastructure errors before publishing")
    approved = (registry or load_registry()).get("benchmarks", {})
    entry = approved.get(result.get("benchmark_fingerprint"))
    require(isinstance(entry, dict) and entry.get("manifest") == result.get("benchmark_manifest"),
            "Benchmark is not in the maintainer-approved compatibility registry")
    try:
        p = Policy(**result["policy"])
    except (TypeError, ValueError) as exc:
        raise SubmissionError("Invalid policy settings") from exc
    require(p.fingerprint == result["policy_fingerprint"] and p.source == result["policy_source"],
            "Policy fingerprint/source does not match settings")
    require(dict(p.budgets) == result["budgets"], "Budget metadata disagrees with the policy")
    require(p.name in {"strict", "vendor", "custom"}, "Invalid policy profile")
    require(type(result.get("concurrency")) is int and result["concurrency"] >= 1, "Invalid concurrency")
    segments = result.get("execution_segments")
    require(isinstance(segments, list) and 0 < len(segments) <= 1000, "Missing execution segments/run identity")
    require(all(isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] for s in segments),
            "Invalid execution segment identity")
    for c in CATEGORIES:
        keys = [str(r.get("key") or r.get("id")) for r in result["items"][c]]
        require(set(keys) == set(result["benchmark_manifest"]["selected_keys"][c]), "Wrong task selection")
        for r in result["items"][c]:
            require(isinstance(r.get("raw_text"), str) and r.get("scored") is True,
                    "Missing saved scored response evidence")
    return entry
