from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import warnings
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sixcat.policy import resolve_policy  # noqa: E402


DEFAULT_CANDIDATES = (
    "http://127.0.0.1:8085/v1",
    "http://127.0.0.1:8083/v1",
    "http://127.0.0.1:8000/v1",
    "http://127.0.0.1:30000/v1",
)
DEFAULT_RUN = {
    "limit": 20,
    "max_minutes": 30.0,
    "request_timeout_seconds": 180.0,
}


def normalize_base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    if not base:
        raise ValueError("base URL cannot be empty")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def _has_credential(api_key: str) -> bool:
    return bool(api_key and api_key.casefold() != "none")


def _headers(api_key: str) -> dict[str, str]:
    if not _has_credential(api_key):
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def probe_endpoint(base_url: str, *, api_key: str = "none", timeout: float = 5.0) -> dict[str, Any]:
    normalized = normalize_base_url(base_url)
    request = urllib.request.Request(
        normalized + "/models",
        headers=_headers(api_key),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"base_url": normalized, "reachable": False, "error": str(exc), "models": []}

    data = payload.get("data") if isinstance(payload, dict) else None
    models = []
    if isinstance(data, list):
        for item in data:
            model_id = item.get("id") if isinstance(item, dict) else None
            if isinstance(model_id, str) and model_id and model_id not in models:
                models.append(model_id)
    return {"base_url": normalized, "reachable": True, "models": models}


def discover_endpoints(
    candidates: list[str] | tuple[str, ...],
    *,
    api_key: str = "none",
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    normalized_candidates = list(dict.fromkeys(normalize_base_url(candidate) for candidate in candidates))
    if _has_credential(api_key) and len(normalized_candidates) != 1:
        raise ValueError("an API credential requires exactly one explicit single endpoint")
    for normalized in normalized_candidates:
        probe = probe_endpoint(normalized, api_key=api_key, timeout=timeout)
        if probe.get("reachable"):
            discovered.append(probe)
    return discovered


def select_target(discovered: list[dict[str, Any]], requested_model: str | None) -> dict[str, Any]:
    if not discovered:
        return {"status": "no_endpoint", "endpoints": []}
    if len(discovered) > 1:
        return {
            "status": "ambiguous_endpoints",
            "endpoints": [item.get("base_url") for item in discovered],
            "choices": discovered,
        }

    endpoint = discovered[0]
    models = list(endpoint.get("models") or [])
    if requested_model is not None:
        if requested_model not in models:
            return {
                "status": "model_not_found",
                "base_url": endpoint["base_url"],
                "requested_model": requested_model,
                "models": models,
            }
        model = requested_model
    elif len(models) == 1:
        model = models[0]
    elif not models:
        return {"status": "no_models", "base_url": endpoint["base_url"], "models": []}
    else:
        return {"status": "ambiguous_models", "base_url": endpoint["base_url"], "models": models}

    return {
        "status": "ready",
        "base_url": endpoint["base_url"],
        "model": model,
        "models": models,
    }


def policy_preview(model: str) -> dict[str, Any]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = resolve_policy("vendor", model)
    return {
        "recommended_policy": "vendor" if resolved.name == "vendor" else "strict",
        "resolved_policy": resolved.to_dict(),
        "policy_source": resolved.source,
        "policy_fingerprint": resolved.fingerprint,
        "warnings": [str(item.message) for item in caught],
    }


def build_preflight(
    candidates: list[str] | tuple[str, ...],
    *,
    requested_model: str | None = None,
    api_key: str = "none",
    timeout: float = 5.0,
) -> dict[str, Any]:
    normalized_candidates = list(dict.fromkeys(normalize_base_url(candidate) for candidate in candidates))
    if _has_credential(api_key) and len(normalized_candidates) != 1:
        return {
            "status": "credential_requires_single_endpoint",
            "endpoints": normalized_candidates,
            "discovered": [],
            "default_run": dict(DEFAULT_RUN),
            "error": "Set exactly one --base-url or SIXCAT_BASE_URL before using an API credential.",
        }
    discovered = discover_endpoints(normalized_candidates, api_key=api_key, timeout=timeout)
    target = select_target(discovered, requested_model)
    result: dict[str, Any] = {
        **target,
        "discovered": discovered,
        "default_run": dict(DEFAULT_RUN),
    }
    if target.get("status") == "ready":
        result.update(policy_preview(str(target["model"])))
    return result


def _human(result: dict[str, Any]) -> str:
    status = result.get("status")
    if status != "ready":
        return json.dumps(result, indent=2, ensure_ascii=False)
    policy = result["resolved_policy"]
    lines = [
        f"endpoint: {result['base_url']}",
        f"model: {result['model']}",
        f"recommended policy: {result['recommended_policy']}",
        f"source: {result['policy_source']}",
        f"policy fingerprint: {result['policy_fingerprint']}",
        "sampling: "
        f"temperature={policy['temperature']} top_p={policy['top_p']} "
        f"top_k={policy['top_k']} min_p={policy['min_p']} thinking={policy['thinking']}",
        f"extra: {json.dumps(policy['extra'], sort_keys=True)}",
        f"budgets: {json.dumps(policy['budgets'], sort_keys=True)}",
        "default run: --limit 20 --max-minutes 30",
    ]
    for warning in result.get("warnings") or []:
        lines.append(f"warning: {warning}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect a Sixcat endpoint/model and preview its reviewed policy.")
    parser.add_argument("--base-url", action="append", default=[], help="Endpoint to inspect; repeatable.")
    parser.add_argument("--model", default=None, help="Select one exact ID returned by /v1/models.")
    parser.add_argument("--api-key-env", default="SIXCAT_API_KEY", help="Environment variable holding the API key.")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    configured = os.environ.get("SIXCAT_BASE_URL")
    candidates = list(args.base_url)
    if not candidates and configured:
        candidates.append(configured)
    if not candidates:
        candidates.extend(DEFAULT_CANDIDATES)
    api_key = os.environ.get(args.api_key_env, "none")
    result = build_preflight(
        candidates,
        requested_model=args.model,
        api_key=api_key,
        timeout=args.timeout,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else _human(result))
    return 0 if result.get("status") == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
