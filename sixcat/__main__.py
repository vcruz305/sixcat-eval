from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import ChatClient
from .journal import RunJournal, Session, TimeBudget
from .run import render_table, run_battery


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sixcat", description="Six community categories + one overall score.")
    p.add_argument("--base-url", default="http://127.0.0.1:8085/v1")
    p.add_argument("--model", required=True)
    p.add_argument("--api-key", default="none")
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
    args = p.parse_args(argv)

    limit = None if args.full else args.limit
    log_path = args.log
    if log_path is None:
        if args.out:
            log_path = args.out.with_suffix(".jsonl")
        else:
            log_path = Path("results") / f"{args.model}.jsonl"

    seconds = None if args.max_minutes == 0 else args.max_minutes * 60.0
    budget = TimeBudget(seconds=seconds)
    journal = RunJournal(log_path, resume=not args.no_resume)
    session = Session(journal, budget)
    print(f"log {log_path} resume={not args.no_resume} max_minutes={args.max_minutes}", flush=True)
    try:
        client = ChatClient(args.base_url, args.model, api_key=args.api_key)
        result = run_battery(client, limit=limit, session=session)
    finally:
        journal.close()

    print(render_table(result))
    if args.out:
        slim = {k: v for k, v in result.items() if k != "items"}
        slim["log"] = str(log_path)
        slim["items"] = {
            cat: [{"id": r.get("id") or r.get("key"), "ok": r.get("ok"), "pred": r.get("pred"), "gold": r.get("gold")} for r in rows]
            for cat, rows in result["items"].items()
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(slim, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
