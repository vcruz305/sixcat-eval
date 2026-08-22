from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

from .client import ChatClient
from .journal import RunJournal, Session, TimeBudget
from .policy import resolve_policy
from .report import (
    PARSER_VERSION,
    RESULT_SCHEMA,
    PolicyMismatchError,
    ResultFormatError,
    RunScopeMismatchError,
    compare_results,
    load_result,
    render_both_table,
)
from .run import CATEGORIES, render_table, run_battery


def parse_budget_overrides(specs: list[str]) -> dict[str, int]:
    """Parse repeatable CATEGORY=N overrides with fail-fast validation."""
    budgets: dict[str, int] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"--budget must be CATEGORY=N, got {spec!r}")
        cat, _, raw_value = spec.partition("=")
        cat = cat.strip()
        if cat not in CATEGORIES:
            raise ValueError(f"--budget: unknown category {cat!r}, expected one of {CATEGORIES}")
        try:
            value = int(raw_value.strip())
        except ValueError as exc:
            raise ValueError(f"--budget: {spec!r} is not an integer") from exc
        if value <= 0:
            raise ValueError(f"--budget: {spec!r} must be a positive integer")
        budgets[cat] = value
    return budgets


def _journal_identity(
    *,
    model: str,
    base_url: str,
    policy,
    limit: int | None,
    request_timeout: float,
    skip_code_exec: bool,
) -> dict:
    return {
        "result_schema": RESULT_SCHEMA,
        "parser": PARSER_VERSION,
        "model": model,
        "base_url": base_url.rstrip("/"),
        "policy": policy.name,
        "policy_fingerprint": policy.fingerprint,
        "budgets": dict(policy.budgets),
        "limit": limit,
        "request_timeout_seconds": float(request_timeout),
        "code_execution": "disabled" if skip_code_exec else "host-guarded",
    }


def _label_path(path: Path, label: str, *, default_suffix: str) -> Path:
    """Insert a policy label before a requested artifact's suffix."""
    if path.suffix:
        return path.with_name(f"{path.stem}.{label}{path.suffix}")
    return path.with_name(f"{path.name}.{label}{default_suffix}")


def _slim_result(result: dict, log_path: Path) -> dict:
    """Return a detached, JSON-ready result without projecting away row receipts.

    The historical name is retained for callers, but item rows are intentionally not
    slimmed: grader inputs and request provenance are part of the result contract.
    """
    saved = copy.deepcopy(result)
    saved["log"] = str(log_path)
    return saved


def _write_result(result: dict, out_path: Path, log_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_slim_result(result, log_path), indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")


def _run_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="sixcat", description="Six community categories + one overall score.")
    p.add_argument("--base-url", default="http://127.0.0.1:8085/v1")
    p.add_argument("--model", required=True)
    p.add_argument(
        "--api-key",
        default=os.environ.get("SIXCAT_API_KEY", "none"),
        help="API key. Defaults to SIXCAT_API_KEY, then 'none' for local servers.",
    )
    p.add_argument(
        "--policy",
        choices=("strict", "vendor", "both"),
        default="strict",
        help="Inference policy to run. 'both' runs strict then vendor with separate artifacts.",
    )
    p.add_argument("--policy-file", type=Path, default=None, help="Reviewed vendor policy mapping JSON.")
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override sampling seed. Vendor default 1; omit to use the reviewed policy.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Items per dataset. Default 20 (~180 items).",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Ignore --limit and run the entire shipped sets (740 items).",
    )
    p.add_argument(
        "--max-minutes",
        type=float,
        default=30.0,
        help="Stop starting new items after this many minutes. Default 30. 0 = no cap.",
    )
    p.add_argument(
        "--request-timeout",
        type=float,
        default=180.0,
        help="Per-request HTTP timeout in seconds. Default 180; raise for long thinking completions.",
    )
    p.add_argument(
        "--skip-code-exec",
        action="store_true",
        help="Skip HumanEval model-code execution (enabled by default in a guarded host subprocess).",
    )
    p.add_argument("--out", type=Path, default=None, help="Final JSON summary.")
    p.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Live JSONL log (one line per item). Default: <out>.jsonl or results/<model>.jsonl",
    )
    p.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore an existing log and start a new one.",
    )
    p.add_argument(
        "--budget",
        action="append",
        default=[],
        metavar="CATEGORY=N",
        help="Override a category's max_tokens. Repeatable, "
        "e.g. --budget math=2048 --budget code=3072. Unknown category names are rejected.",
    )
    args = p.parse_args(argv)
    if args.request_timeout <= 0:
        p.error("--request-timeout must be positive")

    try:
        budgets = parse_budget_overrides(args.budget)
    except ValueError as exc:
        p.error(str(exc))

    limit = None if args.full else args.limit
    requested_log = args.log
    if requested_log is None:
        if args.out:
            requested_log = args.out.with_suffix(".jsonl")
        else:
            requested_log = Path("results") / f"{args.model}.jsonl"

    seconds = None if args.max_minutes == 0 else args.max_minutes * 60.0
    policy_names = ("strict", "vendor") if args.policy == "both" else (args.policy,)
    if args.policy == "both":
        requested_out = args.out or (Path("results") / f"{args.model}.json")
        run_paths = {
            name: (
                _label_path(requested_out, name, default_suffix=".json"),
                _label_path(requested_log, name, default_suffix=".jsonl"),
            )
            for name in policy_names
        }
    else:
        run_paths = {args.policy: (args.out, requested_log)}

    completed_results: dict[str, dict] = {}
    for policy_name in policy_names:
        out_path, log_path = run_paths[policy_name]
        if args.policy == "both":
            print(f"=== {policy_name.upper()} ===", flush=True)
        try:
            policy = resolve_policy(
                policy_name,
                args.model,
                budget_overrides=budgets or None,
                seed=args.seed,
                policy_file=args.policy_file,
            )
        except ValueError as exc:
            p.error(str(exc))
        identity = _journal_identity(
            model=args.model,
            base_url=args.base_url,
            policy=policy,
            limit=limit,
            request_timeout=args.request_timeout,
            skip_code_exec=args.skip_code_exec,
        )
        try:
            journal = RunJournal(log_path, resume=not args.no_resume, identity=identity)
        except ValueError as exc:
            p.error(str(exc))
        budget = TimeBudget(seconds=seconds)
        session = Session(journal, budget)
        print(f"log {log_path} resume={not args.no_resume} max_minutes={args.max_minutes}", flush=True)
        try:
            client = ChatClient(
                args.base_url,
                args.model,
                policy,
                api_key=args.api_key,
                timeout=args.request_timeout,
            )
            result = run_battery(
                client,
                limit=limit,
                session=session,
                skip_code_exec=args.skip_code_exec,
            )
        finally:
            journal.close()

        completed_results[policy_name] = result
        print(render_table(result))
        if out_path is not None:
            _write_result(result, out_path, log_path)
    if args.policy == "both":
        try:
            combined = render_both_table(completed_results["strict"], completed_results["vendor"])
        except RunScopeMismatchError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print(
                render_both_table(
                    completed_results["strict"],
                    completed_results["vendor"],
                    allow_mismatch=True,
                )
            )
            return 2
        print(combined)
    return 0


def _compare_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sixcat compare",
        description="Compare two sixcat result JSON files with B-minus-A deltas.",
    )
    parser.add_argument("a", type=Path, metavar="A.json")
    parser.add_argument("b", type=Path, metavar="B.json")
    parser.add_argument(
        "--allow-mismatch",
        action="store_true",
        help="Display descriptive deltas despite policy or run-scope mismatch (not comparable).",
    )
    args = parser.parse_args(argv)
    try:
        a = load_result(args.a)
        b = load_result(args.b)
        table, notices = compare_results(a, b, allow_mismatch=args.allow_mismatch)
    except (ResultFormatError, PolicyMismatchError, RunScopeMismatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for notice in notices:
        print(notice, file=sys.stderr)
    print(table)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "compare":
        return _compare_main(args[1:])
    return _run_main(args)


if __name__ == "__main__":
    sys.exit(main())
