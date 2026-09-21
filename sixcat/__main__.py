from __future__ import annotations

import argparse
import copy
import json
import math
from .storage import atomic_write_json
from .manifest import ATTEMPT_POLICY, SCHEDULE, benchmark_manifest, observed_server_identity
from .runtime import deadline_scope
import os
import re
import sys
from pathlib import Path

from .client import ChatClient, fetch_server_props
from .journal import RunJournal, Session, TimeBudget
from .policy import custom_policy, override_thinking, resolve_policy, vendor_family_catalog
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
from .run import CATEGORIES, render_table, retry_plan_from_result, run_battery
from .selection import SELECTION_FINGERPRINT, SELECTION_PROFILE


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
    transport: str = "openai",
    server_identity: dict | None = None,
    artifact_id: str | None = None,
) -> dict:
    identity = {
        "result_schema": RESULT_SCHEMA,
        "attempt_policy": ATTEMPT_POLICY,
        "schedule": SCHEDULE,
        "benchmark_fingerprint": benchmark_manifest(limit, skip_code_exec)["fingerprint"],
        "server_identity": server_identity,
        "artifact_id": artifact_id,
        "parser": PARSER_VERSION,
        "model": model,
        "base_url": base_url.rstrip("/"),
        "policy": policy.name,
        "policy_fingerprint": policy.fingerprint,
        "budgets": dict(policy.budgets),
        "limit": limit,
        "limit_scope": "per_category",
        "selection_profile": SELECTION_PROFILE,
        "selection_fingerprint": SELECTION_FINGERPRINT,
        "request_timeout_seconds": float(request_timeout),
        "code_execution": "disabled" if skip_code_exec else "host-guarded",
    }
    if server_identity and server_identity.get("verified_upstream"):
        identity["verified_upstream"] = server_identity["verified_upstream"]
    if (transport or "openai") != "openai":
        identity["transport"] = transport
    return identity


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
    atomic_write_json(out_path, _slim_result(result, log_path))
    print(f"\nwrote {out_path}")


def _run_main(argv: list[str]) -> int:
    explicit_concurrency = any(
        token == "--concurrency" or token.startswith("--concurrency=") for token in argv
    )
    p = argparse.ArgumentParser(prog="sixcat", description="Six community categories + one overall score.")
    p.add_argument("--base-url", default="http://127.0.0.1:8085/v1")
    p.add_argument("--model", required=True)
    p.add_argument("--artifact-id", default=None, help="Operator-provided model/quant revision or SHA256; bound into resume identity.")
    p.add_argument(
        "--api-key",
        default=os.environ.get("SIXCAT_API_KEY", "none"),
        help="API key. Defaults to SIXCAT_API_KEY, then 'none' for local servers.",
    )
    p.add_argument(
        "--policy",
        choices=("strict", "vendor", "both", "custom"),
        default="strict",
        help="Sampling mode: strict baseline, vendor-recommended settings, both, or explicit custom settings.",
    )
    p.add_argument("--policy-file", type=Path, default=None, help="Reviewed vendor policy mapping JSON.")
    p.add_argument(
        "--policy-family",
        default=None,
        help="Apply this reviewed vendor family even if the model ID does not match.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional integer for repeatable sampling when the endpoint honors seeds. Vendor-recommended default is 1; some endpoints ignore seeds.",
    )
    p.add_argument("--temperature", type=float, default=None, help="Custom mode temperature (required).")
    p.add_argument("--top-p", type=float, default=None, help="Custom mode nucleus-sampling cutoff.")
    p.add_argument("--top-k", type=int, default=None, help="Custom mode top-k cutoff.")
    p.add_argument("--min-p", type=float, default=None, help="Custom mode minimum-token probability cutoff.")
    p.add_argument(
        "--thinking",
        choices=("on", "off"),
        default=None,
        help="Explicit reasoning/thinking toggle for any sampling mode.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Scored items per category. Default 20 (~120 total across six categories).",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Ignore --limit and run the entire shipped sets (884 items).",
    )
    p.add_argument(
        "--max-minutes",
        type=float,
        default=30.0,
        help="Total invocation deadline including preflight and in-flight requests. Default 30. 0 = no cap.",
    )
    p.add_argument(
        "--request-timeout",
        type=float,
        default=1800.0,
        help="Per-request HTTP timeout in seconds. Default 1800 for long thinking completions.",
    )
    p.add_argument(
        "--ctx",
        type=int,
        default=None,
        help="Operator context override in tokens. Recorded as configured, not detected. Does not change scoring or --max-minutes.",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="In-flight scored items. Default 1; use --auto-concurrency to discover the serving throughput knee first.",
    )
    p.add_argument(
        "--auto-concurrency",
        action="store_true",
        help="Run an unscored synthetic concurrency curve first, then use its recommended concurrency for the scored run.",
    )
    p.add_argument("--concurrency-candidates", default="1,2,4,8")
    p.add_argument("--calibration-seconds", type=float, default=60.0)
    p.add_argument("--calibration-knee-fraction", type=float, default=0.90)
    p.add_argument("--calibration-prompt-words", type=int, default=256)
    p.add_argument("--calibration-max-tokens", type=int, default=64)
    p.add_argument(
        "--transport",
        choices=("openai", "stdio"),
        default="openai",
        help="openai = HTTP /v1/chat/completions. stdio = JSONL complete/answer on stdout/stdin for harnesses (ZCode, etc.).",
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
        "--retry",
        choices=("failed", "remaining", "incomplete"),
        default=None,
        help=(
            "Merge another pass into the same --log/--out instead of a full rerun. "
            "remaining=unscored items, failed=previous FAIL rows only, "
            "incomplete=failed plus remaining. Requires resume (not --no-resume)."
        ),
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
    if not math.isfinite(args.request_timeout) or args.request_timeout <= 0:
        p.error("--request-timeout must be finite and positive")
    if not math.isfinite(args.max_minutes) or args.max_minutes < 0:
        p.error("--max-minutes must be finite and non-negative")
    if args.limit <= 0:
        p.error("--limit must be positive (use --full for the entire corpus)")
    if args.ctx is not None and args.ctx <= 0:
        p.error("--ctx must be a positive token count")
    if args.concurrency < 1:
        p.error("--concurrency must be >= 1")
    if args.auto_concurrency and explicit_concurrency:
        p.error("--auto-concurrency and an explicit --concurrency are mutually exclusive")
    if args.auto_concurrency and args.transport != "openai":
        p.error("--auto-concurrency requires --transport openai")
    if args.transport == "stdio" and args.concurrency != 1:
        p.error("--transport stdio requires --concurrency 1")
    if not math.isfinite(args.calibration_seconds) or args.calibration_seconds <= 0:
        p.error("--calibration-seconds must be finite and positive")
    if not 0.5 <= args.calibration_knee_fraction <= 1.0:
        p.error("--calibration-knee-fraction must be between 0.5 and 1.0")
    if args.calibration_prompt_words < 16 or args.calibration_max_tokens < 2:
        p.error("--calibration-prompt-words must be >= 16 and --calibration-max-tokens >= 2")
    protocol_out = sys.stdout
    if args.transport == "stdio":
        args.base_url = "stdio://harness"
        sys.stdout = sys.stderr

    try:
        budgets = parse_budget_overrides(args.budget)
    except ValueError as exc:
        p.error(str(exc))

    custom_values = (args.temperature, args.top_p, args.top_k, args.min_p)
    if args.policy == "custom" and args.temperature is None:
        p.error("--policy custom requires --temperature")
    if args.policy != "custom" and any(value is not None for value in custom_values):
        p.error("--temperature/--top-p/--top-k/--min-p require --policy custom")
    if args.policy_family and args.policy not in {"vendor", "both"}:
        p.error("--policy-family requires --policy vendor or --policy both")

    limit = None if args.full else args.limit
    model_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.model).strip(".") or "model"
    requested_log = args.log
    if requested_log is None:
        if args.out:
            requested_log = args.out.with_suffix(".jsonl")
        else:
            requested_log = Path("results") / f"{model_slug}.jsonl"

    if args.retry and args.no_resume:
        p.error("--retry merges into an existing journal; do not pass --no-resume")

    seconds = None if args.max_minutes == 0 else args.max_minutes * 60.0
    policy_names = ("strict", "vendor") if args.policy == "both" else (args.policy,)
    if args.policy == "both":
        requested_out = args.out or (Path("results") / f"{model_slug}.json")
        run_paths = {
            name: (
                _label_path(requested_out, name, default_suffix=".json"),
                _label_path(requested_log, name, default_suffix=".jsonl"),
            )
            for name in policy_names
        }
    else:
        run_paths = {args.policy: (args.out, requested_log)}

    for out_path, log_path in run_paths.values():
        if out_path is not None and out_path.resolve() == log_path.resolve():
            p.error("--out and --log must name different files")
        if args.retry and not Path(log_path).exists():
            p.error(f"--retry requires an existing journal at {log_path}")
    completed_results: dict[str, dict] = {}
    invocation_budget = TimeBudget(seconds=seconds)
    for policy_name in policy_names:
        out_path, log_path = run_paths[policy_name]
        if args.policy == "both":
            print(f"=== {policy_name.upper()} ===", flush=True)
        try:
            if policy_name == "custom":
                policy = custom_policy(
                    temperature=args.temperature,
                    top_p=args.top_p,
                    top_k=args.top_k,
                    min_p=args.min_p,
                    thinking=args.thinking == "on",
                    seed=args.seed,
                    budget_overrides=budgets or None,
                )
            else:
                policy = resolve_policy(
                    policy_name,
                    args.model,
                    budget_overrides=budgets or None,
                    seed=args.seed,
                    policy_file=args.policy_file,
                    family=args.policy_family if policy_name == "vendor" else None,
                )
            if args.thinking is not None:
                policy = override_thinking(policy, args.thinking == "on")
        except ValueError as exc:
            p.error(str(exc))
        client = ChatClient(
            args.base_url, args.model, policy, api_key=args.api_key,
            timeout=args.request_timeout, transport=args.transport,
            stdio_in=sys.stdin if args.transport == "stdio" else None,
            stdio_out=protocol_out if args.transport == "stdio" else None,
        )
        with deadline_scope(invocation_budget.deadline):
            client.server_props = fetch_server_props(args.base_url, args.api_key) if args.transport == "openai" else {"source": "stdio"}
        client.server_identity = observed_server_identity(client.server_props, args.model)
        client.artifact_id = args.artifact_id
        identity = _journal_identity(
            model=args.model,
            base_url=args.base_url,
            policy=policy,
            limit=limit,
            request_timeout=args.request_timeout,
            skip_code_exec=args.skip_code_exec,
            transport=args.transport,
            server_identity=client.server_identity,
            artifact_id=args.artifact_id,
        )
        if args.retry and not Path(log_path).exists():
            p.error(f"--retry requires an existing journal at {log_path}")
        try:
            journal = RunJournal(log_path, resume=not args.no_resume, identity=identity)
        except ValueError as exc:
            p.error(str(exc))
        budget = invocation_budget
        session = Session(
            journal,
            budget,
            retry_failed=args.retry in {"failed", "incomplete"},
            include_remaining=args.retry != "failed",
            retry_mode=args.retry,
            concurrency=args.concurrency,
        )
        print(
            f"log {log_path} resume={not args.no_resume} max_minutes={args.max_minutes} concurrency={args.concurrency}",
            flush=True,
        )
        try:
            result = run_battery(
                client,
                limit=limit,
                session=session,
                skip_code_exec=args.skip_code_exec,
                configured_ctx=args.ctx,
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
    return 2 if any(result.get("policy_probe") not in (None, "ok") or result.get("errors")
                    for result in completed_results.values()) else 0


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
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    parser.add_argument("--out", type=Path, help="Optional machine-readable paired comparison (not a benchmark result).")
    args = parser.parse_args(argv)
    if not 100 <= args.bootstrap_samples <= 100000:
        parser.error("--bootstrap-samples must be between 100 and 100000")
    if args.out and args.out.resolve() in {args.a.resolve(), args.b.resolve()}:
        parser.error("comparison output must not overwrite either input")
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
    analysis = None
    if a.get("items") and b.get("items"):
        from .analysis import paired_comparison, render_paired
        try:
            # Re-run the strict gate even when a descriptive override was requested.
            compare_results(a, b, allow_mismatch=False)
            analysis = paired_comparison(a, b, samples=args.bootstrap_samples, seed=args.bootstrap_seed)
            print(render_paired(analysis))
        except (ValueError, PolicyMismatchError, RunScopeMismatchError) as exc:
            print(f"Paired inference omitted: {exc}", file=sys.stderr)
    if args.out:
        atomic_write_json(args.out, {"kind": "sixcat-comparison", "a": str(args.a), "b": str(args.b),
                                    "notices": notices, "paired": analysis})
    return 0


def _retry_plan_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sixcat retry-plan",
        description="Print merge argv for an existing Sixcat result JSON.",
    )
    parser.add_argument("result", type=Path)
    parser.add_argument("--retry", choices=("failed", "remaining", "incomplete"), default="failed")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.result.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("result must be a JSON object")
        plan = retry_plan_from_result(document, retry=args.retry, result_path=str(args.result))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    else:
        print("model", plan["model"])
        print("retry", plan["retry"])
        print("remaining", (plan["continuation"] or {}).get("remaining"))
        print("failed", (plan["continuation"] or {}).get("failed"))
        print("argv", " ".join(plan["argv"]))
    return 0


def _families_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sixcat families",
        description="List reviewed vendor families and suggest a match for an unmapped model.",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--group", choices=("qwen", "deepseek", "glm", "other"), default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        catalog = vendor_family_catalog(model=args.model, group=args.group)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(catalog, indent=2, ensure_ascii=False))
        return 0
    mapping = catalog.get("mapping")
    if mapping:
        print(f"mapped {mapping['family']} ({mapping['label']})")
    elif args.model:
        print(f"unmapped {args.model}")
    suggested = catalog.get("suggested") or []
    if suggested:
        print("suggested:")
        for item in suggested:
            print(f"  {item['label']}")
    print("families:")
    for item in catalog.get("families") or []:
        print(f"  {item['label']}")
    return 0


def _preflight_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sixcat preflight",
        description="Detect served context and estimate ETA without scoring.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8085/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default=os.environ.get("SIXCAT_API_KEY", "none"))
    parser.add_argument("--ctx", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--skip-code-exec", action="store_true")
    parser.add_argument("--thinking", choices=("on", "off"), default="off")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.ctx is not None and args.ctx <= 0:
        parser.error("--ctx must be a positive token count")
    from .client import fetch_server_props
    from .context_preflight import assemble_preflight, format_preflight
    from .policy import STRICT_BUDGETS, THINKING_BUDGETS
    from .run import expected_scored_items

    server_props = fetch_server_props(args.base_url, args.api_key)
    budgets = THINKING_BUDGETS if args.thinking == "on" else STRICT_BUDGETS
    limit = None if args.full else args.limit
    preflight = assemble_preflight(
        requested_model=args.model,
        server_props=server_props,
        probe=None,
        n_items=expected_scored_items(limit, skip_code_exec=args.skip_code_exec),
        output_reserve=max(budgets.values()),
        configured_ctx=args.ctx,
        thinking=args.thinking == "on",
    )
    if args.json:
        print(json.dumps(preflight, indent=2, ensure_ascii=False))
    else:
        print(format_preflight(preflight))
    return 0


def _dispatch(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"rescore", "export-evalplus"}:
        from .offline import main as offline_main
        return offline_main(args[1:], export=args[0] == "export-evalplus")
    if args and args[0] == "repeat":
        from .repeat import main as repeat_main
        return repeat_main(args[1:])
    if args and args[0] == "compare":
        return _compare_main(args[1:])
    if args and args[0] == "retry-plan":
        return _retry_plan_main(args[1:])
    if args and args[0] == "families":
        return _families_main(args[1:])
    if args and args[0] == "preflight":
        return _preflight_main(args[1:])
    return _run_main(args)


def main(argv: list[str] | None = None) -> int:
    stdout = sys.stdout
    try:
        return _dispatch(argv)
    finally:
        sys.stdout = stdout


if __name__ == "__main__":
    sys.exit(main())
