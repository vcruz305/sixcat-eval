from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CATEGORY_ORDER = ("knowledge", "math", "truth", "instruct", "code", "tools")


def _read_rows(path: Path) -> tuple[list[dict[str, Any]], list[int], dict[str, Any] | None]:
    rows: list[dict[str, Any]] = []
    invalid_lines: list[int] = []
    run_identity: dict[str, Any] | None = None
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return rows, invalid_lines, run_identity
    lines = text.splitlines()
    nonempty_indices = [index for index, line in enumerate(lines) if line.strip()]
    last_nonempty = nonempty_indices[-1] if nonempty_indices else None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            # An active writer can leave one unterminated tail line. Any completed or
            # interior malformed line is journal corruption and must stay visible.
            if index == last_nonempty and not text.endswith(("\n", "\r")):
                continue
            invalid_lines.append(index + 1)
            continue
        if isinstance(item, dict):
            if "_sixcat_run" in item:
                candidate = item.get("_sixcat_run")
                if not isinstance(candidate, dict) or (run_identity is not None and candidate != run_identity):
                    invalid_lines.append(index + 1)
                else:
                    run_identity = candidate
                continue
            rows.append(item)
        else:
            invalid_lines.append(index + 1)
    return rows, invalid_lines, run_identity


def summarize_journal(path: str | Path) -> dict[str, Any]:
    journal = Path(path)
    rows, invalid_lines, run_identity = _read_rows(journal)
    category_counts: dict[str, dict[str, int]] = {}
    for category in CATEGORY_ORDER:
        selected = [row for row in rows if row.get("cat") == category]
        if selected:
            passed = sum(1 for row in selected if row.get("ok") is True)
            category_counts[category] = {
                "rows": len(selected),
                "passed": passed,
                "failed": len(selected) - passed,
            }

    timestamps = [
        float(row["ts"])
        for row in rows
        if isinstance(row.get("ts"), (int, float)) and not isinstance(row.get("ts"), bool)
    ]
    latest = None
    if rows:
        last = rows[-1]
        latest = f"{last.get('cat', '?')}/{last.get('key') or last.get('id') or '?'}"
    passed = sum(1 for row in rows if row.get("ok") is True)
    return {
        "log": str(journal),
        "run_identity": run_identity,
        "rows": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "truncated": sum(1 for row in rows if row.get("finish") == "length"),
        "loop_failures": sum(1 for row in rows if row.get("loop") is True),
        "low_confidence": sum(1 for row in rows if row.get("parse_confidence") == "low"),
        "invalid_lines": invalid_lines,
        "latest": latest,
        "elapsed_s": max(timestamps) - min(timestamps) if timestamps else None,
        "categories": category_counts,
    }


def merge_final(summary: dict[str, Any], result_path: str | Path | None) -> dict[str, Any]:
    if result_path is None:
        return summary
    path = Path(result_path)
    if not path.exists():
        return summary
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return summary
    if not isinstance(result, dict):
        return summary
    merged = dict(summary)
    merged["final"] = {
        "path": str(path),
        "model": result.get("model"),
        "policy": (result.get("policy") or {}).get("name") if isinstance(result.get("policy"), dict) else None,
        "policy_fingerprint": result.get("policy_fingerprint"),
        "overall": result.get("overall"),
        "overall_flags": result.get("overall_flags"),
        "speed": result.get("speed"),
        "timed_out": result.get("timed_out"),
    }
    return merged


def _human(summary: dict[str, Any]) -> str:
    categories = " ".join(
        f"{category}={counts['rows']}({counts['passed']}p/{counts['failed']}f)"
        for category, counts in summary["categories"].items()
    ) or "none"
    elapsed = summary.get("elapsed_s")
    elapsed_cell = f"{elapsed:.1f}s" if isinstance(elapsed, (int, float)) else "n/a"
    line = (
        f"rows={summary['rows']} pass={summary['passed']} fail={summary['failed']} "
        f"trunc={summary['truncated']} loops={summary['loop_failures']} "
        f"low={summary['low_confidence']} invalid={len(summary['invalid_lines'])} "
        f"elapsed={elapsed_cell} latest={summary['latest'] or 'n/a'}"
    )
    output = [line, f"categories: {categories}"]
    identity = summary.get("run_identity")
    if isinstance(identity, dict):
        output.append(
            "identity: "
            f"model={identity.get('model')} policy={identity.get('policy')} "
            f"fp={identity.get('policy_fingerprint')} limit={identity.get('limit')}"
        )
    final = summary.get("final")
    if isinstance(final, dict):
        output.append(
            "final: "
            f"policy={final.get('policy')} fp={final.get('policy_fingerprint')} "
            f"overall={json.dumps(final.get('overall'), sort_keys=True)} "
            f"flags={json.dumps(final.get('overall_flags'))} timed_out={final.get('timed_out')}"
        )
    return "\n".join(output)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize a live Sixcat JSONL journal safely.")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--result", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = merge_final(summarize_journal(args.log), args.result)
    print(json.dumps(summary, indent=2, ensure_ascii=False) if args.json else _human(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
