from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sixcat.client import ChatClient, fetch_server_props
from sixcat.journal import RunJournal, Session, TimeBudget
from sixcat.policy import THINKING_BUDGETS, probe_policy, resolve_policy
from sixcat.report import PARSER_VERSION, RESULT_SCHEMA
from sixcat.run import run_truth
from sixcat.score import category_stats, extract_mc_letter_conf


DEFAULT_BASE_URL = "http://127.0.0.1:8110/v1"
DEFAULT_MODEL = "ornith-nomtp"
DEFAULT_OUT = Path("results/phase3_vendor_truth_calibration_high_v2.json")
DEFAULT_LOG = Path("results/phase3_vendor_truth_calibration_high_v2.jsonl")
EXPECTED_LIMIT = 20
EXPECTED_SEED = 1
CALIBRATION_BUDGET = 3072
REQUIRED_ROW_FIELDS = frozenset(
    {
        "cat",
        "key",
        "id",
        "ok",
        "pred",
        "gold",
        "finish",
        "ctok",
        "ptok",
        "request_params",
        "parse_confidence",
        "raw_text",
        "reasoning_content",
        "ts",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_recommendation(
    category_stats: dict[str, Any],
    *,
    starting_budget: int,
    require_zero_truncation_floor: bool = False,
) -> dict[str, Any]:
    """Derive headroom from uncensored tokens, adding max+1 only for zero-truncation acceptance."""
    if category_stats.get("truncated"):
        raise ValueError("cannot derive a truth budget from truncated rows")
    p95 = category_stats.get("ctok_p95")
    if not isinstance(p95, (int, float)):
        raise ValueError("cannot derive a truth budget without ctok_p95")
    observed_max = category_stats.get("ctok_max")
    ceil_2xp95 = math.ceil(2 * p95)
    formula_minimum = max(starting_budget, ceil_2xp95)
    zero_truncation_floor = None
    if require_zero_truncation_floor:
        if isinstance(observed_max, bool) or not isinstance(observed_max, int):
            raise ValueError("cannot derive a zero-truncation floor without integer ctok_max")
        zero_truncation_floor = observed_max + 1
    return {
        "ctok_p95": p95,
        "ctok_max": observed_max,
        "ceil_2xp95": ceil_2xp95,
        "starting_thinking_budget": starting_budget,
        "zero_truncation_floor": zero_truncation_floor,
        "recommended_truth_budget": max(
            formula_minimum,
            zero_truncation_floor if zero_truncation_floor is not None else formula_minimum,
        ),
    }


def acceptance_errors(result: dict[str, Any], *, expected_n: int = EXPECTED_LIMIT) -> list[str]:
    """Return deterministic, row-specific failures for the truth calibration gate."""
    rows = result.get("rows") or []
    stats = result.get("category_stats") or {}
    budget = result.get("budget")
    errors: list[str] = []

    if result.get("timed_out") is not False:
        errors.append("timed_out must be false")
    if len(rows) != expected_n:
        errors.append(f"expected {expected_n} rows, got {len(rows)}")
    if stats.get("n") != len(rows):
        errors.append(f"category_stats.n={stats.get('n')!r} does not match rows={len(rows)}")

    identities = [(row.get("cat"), row.get("key")) for row in rows]
    if len(set(identities)) != len(identities):
        errors.append("truth row identities are not unique")
    expected_identities = {("truth", f"tqa:{index}") for index in range(expected_n)}
    if set(identities) != expected_identities:
        missing = sorted(expected_identities.difference(identities))
        extra = sorted(set(identities).difference(expected_identities), key=repr)
        if missing:
            errors.append("missing truth rows: " + ", ".join(f"{cat}/{key}" for cat, key in missing))
        if extra:
            errors.append("unexpected rows: " + ", ".join(f"{cat}/{key}" for cat, key in extra))

    truncated = [
        f"{row.get('cat')}/{row.get('key')}"
        for row in rows
        if row.get("finish") == "length"
    ]
    if truncated:
        errors.append("truncated rows: " + ", ".join(truncated))
    if stats.get("truncated") != len(truncated):
        errors.append(
            f"category_stats.truncated={stats.get('truncated')!r} does not match rows={len(truncated)}"
        )
    if stats.get("parse_confidence_missing") != 0:
        errors.append(
            "category_stats.parse_confidence_missing must be 0, got "
            f"{stats.get('parse_confidence_missing')!r}"
        )

    for row in rows:
        label = f"{row.get('cat')}/{row.get('key')}"
        missing_fields = sorted(REQUIRED_ROW_FIELDS.difference(row))
        if missing_fields:
            errors.append(f"{label} missing fields: {', '.join(missing_fields)}")
        if row.get("id") != row.get("key"):
            errors.append(f"{label} id does not match key")
        request_params = row.get("request_params")
        if not isinstance(request_params, dict):
            errors.append(f"{label} request_params is not an object")
        else:
            if request_params.get("max_tokens") != budget:
                errors.append(
                    f"{label} max_tokens={request_params.get('max_tokens')!r}, expected {budget!r}"
                )
            if request_params.get("enable_thinking") is not True:
                errors.append(f"{label} enable_thinking is not true")
            if request_params.get("seed") != EXPECTED_SEED:
                errors.append(
                    f"{label} seed={request_params.get('seed')!r}, expected {EXPECTED_SEED}"
                )
        raw_text = row.get("raw_text")
        if isinstance(raw_text, str):
            parsed, confidence = extract_mc_letter_conf(raw_text)
            if row.get("pred") != (parsed or ""):
                errors.append(f"{label} pred cannot be re-derived from raw_text")
            if row.get("parse_confidence") != confidence:
                errors.append(f"{label} parse_confidence cannot be re-derived from raw_text")

    return errors


def _write_result(path: Path, result: dict[str, Any], api_key: str) -> None:
    serialized = json.dumps(result, indent=2, ensure_ascii=False)
    if "api_key" in serialized or (api_key and api_key in serialized):
        raise RuntimeError("refusing to write a calibration artifact containing an API key")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized + "\n", encoding="utf-8")


def run_calibration(args: argparse.Namespace) -> dict[str, Any]:
    if args.model != DEFAULT_MODEL:
        raise ValueError(f"this receipt utility is pinned to model {DEFAULT_MODEL!r}")
    if args.seed != EXPECTED_SEED:
        raise ValueError(f"this receipt utility is pinned to seed {EXPECTED_SEED}")
    if args.budget != CALIBRATION_BUDGET:
        raise ValueError(f"this receipt utility is pinned to truth budget {CALIBRATION_BUDGET}")

    policy = resolve_policy(
        "vendor",
        args.model,
        budget_overrides={"truth": args.budget},
        seed=args.seed,
    )
    if policy.name != "vendor":
        raise RuntimeError(f"vendor policy resolution fell back to {policy.name!r}; aborting")
    if policy.budgets.get("truth") != args.budget:
        raise RuntimeError("resolved vendor policy does not carry the requested truth budget")

    client = ChatClient(args.base_url, args.model, policy, api_key=args.api_key)
    started_utc = _utc_now()
    started_epoch = time.time()
    started_monotonic = time.monotonic()
    server = fetch_server_props(client.base_url, client.api_key)
    probe = probe_policy(client)
    if probe.get("status") != "ok":
        raise RuntimeError(f"policy probe failed: {probe.get('reason', 'unknown failure')}")

    journal = RunJournal(args.log, resume=False)
    session = Session(journal, TimeBudget(seconds=None))
    try:
        # One category only. Pass the resolved map because run_truth intentionally accepts
        # budgets explicitly rather than reaching through ChatClient policy state.
        returned_rows = run_truth(
            client,
            limit=EXPECTED_LIMIT,
            session=session,
            budgets=dict(policy.budgets),
        )
        rows = journal.rows_for("truth")
    finally:
        journal.close()

    finished_monotonic = time.monotonic()
    finished_epoch = time.time()
    finished_utc = _utc_now()
    stats = category_stats(rows)
    row_timestamps = [row["ts"] for row in rows if isinstance(row.get("ts"), (int, float))]
    returned_by_identity = {
        (row.get("cat"), row.get("key")): row
        for row in returned_rows
    }
    journal_matches_returned = len(returned_rows) == len(rows) and all(
        {key: value for key, value in row.items() if key != "ts"}
        == returned_by_identity.get((row.get("cat"), row.get("key")))
        for row in rows
    )

    result: dict[str, Any] = {
        "result_schema": RESULT_SCHEMA,
        "parser": PARSER_VERSION,
        "model": client.model,
        "base_url": client.base_url,
        "server": server,
        "policy": policy.to_dict(),
        "source": policy.source,
        "fingerprint": policy.fingerprint,
        "probe": probe,
        "budget": args.budget,
        "limit": EXPECTED_LIMIT,
        "log": str(args.log),
        "rows": rows,
        "category_stats": stats,
        "timed_out": bool(session.stopped),
        "n": len(rows),
        "timestamps": {
            "started_utc": started_utc,
            "finished_utc": finished_utc,
            "started_epoch": started_epoch,
            "finished_epoch": finished_epoch,
            "first_row_epoch": min(row_timestamps) if row_timestamps else None,
            "last_row_epoch": max(row_timestamps) if row_timestamps else None,
        },
        "runtime": {
            "seconds": finished_monotonic - started_monotonic,
            "row_span_seconds": (
                max(row_timestamps) - min(row_timestamps) if len(row_timestamps) >= 2 else 0.0
            ),
        },
        "self_audit": {
            "journal_matches_returned_rows": journal_matches_returned,
            "jsonl_row_count": len(rows),
        },
    }
    errors = acceptance_errors(result)
    if not journal_matches_returned:
        errors.append("JSONL rows do not round-trip the run_truth return rows")
    result["acceptance"] = {"status": "pass" if not errors else "fail", "errors": errors}
    if not errors:
        result["formula"] = derive_recommendation(
            stats,
            starting_budget=THINKING_BUDGETS["truth"],
            require_zero_truncation_floor=True,
        )
    _write_result(args.out, result, args.api_key)

    if errors:
        raise RuntimeError("truth calibration acceptance failed: " + "; ".join(errors))
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the pinned 20-row vendor truth calibration only.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default="none")
    parser.add_argument("--seed", type=int, default=EXPECTED_SEED)
    parser.add_argument("--budget", type=int, default=CALIBRATION_BUDGET)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_calibration(args)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    stats = result["category_stats"]
    formula = result["formula"]
    print(f"wrote {args.out}")
    print(f"wrote {args.log}")
    print(
        "truth "
        f"n={stats['n']} trunc={stats['truncated']} missing={stats['parse_confidence_missing']} "
        f"p95={stats['ctok_p95']} max={stats['ctok_max']}"
    )
    print(
        f"ceil(2*p95)={formula['ceil_2xp95']} "
        f"recommended_truth_budget={formula['recommended_truth_budget']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
