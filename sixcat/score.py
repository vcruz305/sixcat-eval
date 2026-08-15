"""Six-category scoring. Every category is 0–100. Overall is the unweighted mean."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

CATEGORIES = ("knowledge", "math", "truth", "instruct", "code", "tools")

_LETTER = re.compile(r"\b([A-D])\b", re.I)
_HASH_NUM = re.compile(r"####\s*(-?[\d,]+(?:\.\d+)?)")
_LAST_NUM = re.compile(r"(-?[\d,]+(?:\.\d+)?)")


def category_score(rows: Iterable[Mapping[str, Any]]) -> float | None:
    rows = list(rows)
    if not rows:
        return None
    n_ok = sum(1 for r in rows if r.get("ok"))
    return 100.0 * n_ok / len(rows)


def overall_score(cats: Mapping[str, float | None]) -> float:
    missing = [k for k in CATEGORIES if k not in cats]
    if missing:
        raise KeyError(f"missing categories: {missing}")
    vals = [cats[k] for k in CATEGORIES if cats[k] is not None]
    if not vals:
        raise ValueError("no category produced a score")
    return sum(vals) / len(vals)


def extract_mc_letter(text: str) -> str | None:
    if not text:
        return None
    # prefer last "answer is X" / lone letter
    m = re.search(r"(?:answer\s*(?:is|:)\s*)\(?([A-D])\)?", text, re.I)
    if m:
        return m.group(1).upper()
    letters = _LETTER.findall(text)
    if not letters:
        return None
    return letters[-1].upper()


def extract_gsm_number(text: str) -> str | None:
    if not text:
        return None
    m = _HASH_NUM.search(text)
    raw = m.group(1) if m else None
    if raw is None:
        found = _LAST_NUM.findall(text)
        raw = found[-1] if found else None
    if raw is None:
        return None
    raw = raw.replace(",", "")
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw.lstrip("0") or "0" if raw.replace(".", "", 1).isdigit() else raw
