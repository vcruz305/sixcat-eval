from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import ChatClient
from .run import render_table, run_battery


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sixcat", description="Six community categories + one overall score.")
    p.add_argument("--base-url", default="http://127.0.0.1:8085/v1")
    p.add_argument("--model", required=True)
    p.add_argument("--api-key", default="none")
    p.add_argument("--limit", type=int, default=None, help="Cap items per dataset (smoke). Full run omits this.")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    client = ChatClient(args.base_url, args.model, api_key=args.api_key)
    result = run_battery(client, limit=args.limit)
    print(render_table(result))
    if args.out:
        slim = {k: v for k, v in result.items() if k != "items"}
        slim["items"] = {
            cat: [{"id": r.get("id"), "ok": r.get("ok"), "pred": r.get("pred"), "gold": r.get("gold")} for r in rows]
            for cat, rows in result["items"].items()
        }
        args.out.write_text(json.dumps(slim, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
