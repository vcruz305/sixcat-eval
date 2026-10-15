"""Resolve friendly Nous model names from a fresh authenticated catalog.

No inference, static model aliases, model switching, or pricing guarantees.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import os
import re
from typing import Any
from urllib.parse import urlsplit


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _free_evidence(row: dict[str, Any]) -> str | None:
    pricing = row.get("pricing")
    if isinstance(pricing, dict):
        # Explicit nonzero/invalid prices must not be overridden by a free label.
        fields = ("prompt", "completion")
        if any(key in pricing for key in fields):
            try:
                amounts = [Decimal(str(pricing[key])) for key in fields]
            except (KeyError, InvalidOperation, ValueError):
                return None
            if any(not n.is_finite() or n != 0 for n in amounts):
                return None
            return "catalog_zero_prompt_and_completion_price"
    if row.get("billing_mode") == "subscription" or (
        isinstance(pricing, dict) and pricing.get("billing_mode") == "subscription"
    ):
        return "catalog_subscription_billed_not_credit_metered"
    if "free" in _tokens(str(row.get("id", ""))) or "free" in _tokens(str(row.get("name", ""))):
        return "catalog_free_variant_label_not_billing_attestation"
    return None


def match_catalog(query: str, rows: list[dict[str, Any]], *, free_only: bool = False) -> dict[str, Any]:
    """Exact ID first; otherwise all query tokens must match ID/name. Never rank ambiguities away."""
    query = query.strip()
    words = _tokens(query)
    if not words:
        raise ValueError("model query cannot be empty")
    # Model identity and price constraints are independent. A token such as
    # "free" in an ID/display name stays part of the name, not a budget request.
    # Only the explicit option enables catalog-price filtering.
    require_free = bool(free_only)
    wanted = words
    exact = [r for r in rows if isinstance(r, dict) and r.get("id") == query]
    candidates: dict[str, dict[str, Any]] = {}
    for row in exact or rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
            continue
        model = row["id"].strip()
        # Never normalize the wire ID itself or manufacture a :free suffix.
        evidence = _free_evidence(row)
        if require_free and evidence is None:
            continue
        if not exact and not wanted.issubset(_tokens(model + " " + str(row.get("name", "")))):
            continue
        candidates[model] = {"id": model, "name": row.get("name") if isinstance(row.get("name"), str) else None,
                             "free_evidence": evidence}
    matches = [candidates[k] for k in sorted(candidates)]
    status = "resolved" if len(matches) == 1 else "ambiguous" if matches else "not_found"
    return {"status": status, "query": query, "free_required": require_free,
            "model": matches[0]["id"] if len(matches) == 1 else None,
            "candidates": matches, "inference_verified": False, "billing_verified": False,
            "warning": "Catalog labels/pricing are evidence, not verified entitlement or a billing guarantee."}


def fetch_nous_catalog(profile: str) -> tuple[str, list[dict[str, Any]]]:
    """Use Hermes credentials for a single fresh /models GET; never use static fallback lists."""
    from .hermes import resolve_profile_home
    profile_name, home = resolve_profile_home(profile)
    os.environ["HERMES_HOME"] = str(home)
    from hermes_cli.env_loader import load_hermes_dotenv
    load_hermes_dotenv(hermes_home=home)
    from hermes_cli.anon_challenge import background_caller
    from hermes_cli.runtime_provider import resolve_runtime_provider
    # Do not open a login/browser challenge in the middle of model discovery.
    with background_caller():
        runtime = resolve_runtime_provider(requested="nous")
    if runtime.get("provider") != "nous":
        raise RuntimeError("Nous catalog resolution refused a different provider")
    base = str(runtime.get("base_url") or "").rstrip("/")
    parts = urlsplit(base)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise RuntimeError("Nous catalog requires an HTTPS inference URL without embedded credentials/query")
    key = runtime.get("api_key")
    key = key() if callable(key) else key
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError("Hermes could not resolve Nous credentials for model discovery")
    import httpx
    # Never send the token to a redirect target or expose upstream error bodies.
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        response = client.get(base + "/models", headers={"Authorization": "Bearer " + key,
                                                        "Accept": "application/json"})
        if response.status_code != 200:
            raise RuntimeError(f"Nous catalog returned HTTP {response.status_code}; no model selected")
        if len(response.content) > 10_000_000:
            raise RuntimeError("Nous catalog exceeds the 10 MB limit")
        data = response.json()
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Nous catalog returned no model list")
    return profile_name, rows


def resolve_nous_query(profile: str, query: str, *, free_only: bool = False) -> dict[str, Any]:
    name, rows = fetch_nous_catalog(profile)
    return {**match_catalog(query, rows, free_only=free_only),
            "provider": "nous", "profile": name, "catalog_source": "live_authenticated_nous_models"}
