#!/usr/bin/env python3
"""Phase 2 (sixcat v2.1) adjudication: re-run the OLD (v1) MC/GSM parsers against the
raw_text captured by a live v2 run, and list every item where v1 and v2 disagree, for
manual adjudication.

Historical archives cannot be used for this because v1 never persisted raw completion
text for knowledge/truth/math -- only the already-extracted pred survived. See
tests/test_parser_styles.py docstring and sixcat-v2.1-neutrality-plan-2026-08-20.md.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# --- v1 parsers, copied verbatim from the pre-Phase-2 sixcat/score.py ---
_V1_LETTER = re.compile(r"\b([A-L])\b", re.I)
_V1_HASH_NUM = re.compile(r"####\s*(-?[\d,]+(?:\.\d+)?)")
_V1_LAST_NUM = re.compile(r"(-?[\d,]+(?:\.\d+)?)")


def v1_mc_letter(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"(?:answer\s*(?:is|:)\s*)\(?([A-L])\)?", text, re.I)
    if m:
        return m.group(1).upper()
    letters = _V1_LETTER.findall(text)
    if not letters:
        return None
    return letters[-1].upper()


def v1_gsm_number(text: str) -> str | None:
    if not text:
        return None
    m = _V1_HASH_NUM.search(text)
    raw = m.group(1) if m else None
    if raw is None:
        found = _V1_LAST_NUM.findall(text)
        raw = found[-1] if found else None
    if raw is None:
        return None
    raw = raw.replace(",", "")
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw.lstrip("0") or "0" if raw.replace(".", "", 1).isdigit() else raw


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sixcat.score import extract_gsm_number, extract_mc_letter

    path = Path(sys.argv[1] if len(sys.argv) > 1 else "results/phase2_adjudication.json")
    data = json.loads(path.read_text(encoding="utf-8"))

    flips = []
    for cat, parser_v1, parser_v2, is_mc in (
        ("knowledge", v1_mc_letter, extract_mc_letter, True),
        ("truth", v1_mc_letter, extract_mc_letter, True),
        ("math", v1_gsm_number, extract_gsm_number, False),
    ):
        for row in data["items"].get(cat, []):
            raw = row.get("raw_text")
            if raw is None:
                continue
            v1_pred = parser_v1(raw)
            v2_pred = parser_v2(raw)  # recompute fresh -- stored `pred` may predate a code fix
            gold = row.get("gold")
            if v1_pred != v2_pred:
                flips.append(
                    {
                        "cat": cat,
                        "id": row.get("id"),
                        "raw_text": raw,
                        "v1_pred": v1_pred,
                        "v2_pred": v2_pred,
                        "gold": gold,
                        "v1_ok": v1_pred == gold,
                        "v2_ok": v2_pred == gold,
                    }
                )

    print(f"n_items_with_raw_text: {sum(len(data['items'].get(c, [])) for c in ('knowledge', 'truth', 'math'))}")
    print(f"n_flips: {len(flips)}")
    print()
    for f in flips:
        verdict = "FIXED (v1 wrong, v2 right)" if (not f["v1_ok"] and f["v2_ok"]) else (
            "BROKE (v1 right, v2 wrong)" if (f["v1_ok"] and not f["v2_ok"]) else "NEUTRAL (both wrong, different guess)"
        )
        print(f"[{f['cat']}/{f['id']}] gold={f['gold']!r} v1={f['v1_pred']!r} v2={f['v2_pred']!r}  {verdict}")
        print(f"  raw: {f['raw_text']!r}")
        print()

    fixed = sum(1 for f in flips if not f["v1_ok"] and f["v2_ok"])
    broke = sum(1 for f in flips if f["v1_ok"] and not f["v2_ok"])
    neutral = len(flips) - fixed - broke
    print(f"SUMMARY: {len(flips)} flips -> {fixed} fixed, {broke} broke, {neutral} neutral (both wrong)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
