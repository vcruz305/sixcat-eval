"""Command-line glue for challenge-v2 results (offline rescore routing)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .storage import atomic_write_json


def result_profile(argv: list[str]) -> str | None:
    """Selection profile of the result file named in an offline command line, if readable."""
    for token in argv:
        if token.startswith("-"):
            continue
        try:
            document = json.loads(Path(token).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return document.get("selection_profile") if isinstance(document, dict) else None
    return None


def offline_main_v2(argv: list[str], *, export: bool = False) -> int:
    parser = argparse.ArgumentParser(prog="sixcat export-evalplus" if export else "sixcat rescore")
    parser.add_argument("result", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-minutes", type=float, default=30, help="Offline grading deadline; 0 means unlimited.")
    args = parser.parse_args(argv)
    if export:
        parser.error("challenge-v2 Code items are not HumanEval tasks; there is nothing to export for EvalPlus")
    if args.out.resolve() == args.result.resolve() or args.out.exists():
        parser.error("use a NEW output file; the source and existing outputs are never overwritten")
    try:
        from .challenge_v2 import regrade_v2
        from .journal import TimeBudget
        from .report import load_result
        from .runtime import deadline_scope

        document = load_result(args.result)
        budget = TimeBudget(None if args.max_minutes == 0 else args.max_minutes * 60)
        with deadline_scope(budget.deadline):
            result = regrade_v2(document)
        result["regrade_provenance"] = {
            "kind": "offline-no-new-generations", "source": str(args.result),
            "source_sha256": hashlib.sha256(args.result.read_bytes()).hexdigest(),
            "source_parser": document["parser"],
            "source_benchmark_fingerprint": document.get("benchmark_fingerprint"),
        }
        atomic_write_json(args.out, result)
        print(f"rescored saved challenge-v2 first responses into {args.out}; no model requests were made")
    except (OSError, ValueError, KeyError, TimeoutError) as exc:
        parser.error(str(exc))
    return 0
