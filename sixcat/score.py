"""Six-category scoring. Every category is 0–100. Overall is the unweighted mean."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

CATEGORIES = ("knowledge", "math", "truth", "instruct", "code", "tools")
PARSE_CONFIDENCE_VALUES = frozenset({"high", "low", "not_applicable"})
_LOOP_TOKEN = re.compile(r"\w+", re.UNICODE)
_LOOP_NGRAM = 8
_LOOP_MIN_REPEATS = 8

# --- Phase 2 (sixcat v2.1, B4) --------------------------------------------------------
# Position-aware, format-first extraction. The old parsers took the LAST letter/number in
# the text, which rewards terseness and scores a correct "enumerate then conclude" answer
# as wrong purely because the model wrote its reasoning after stating other options. See
# sixcat-v2-neutrality-plan-2026-08-20.md section 1 (B4) for the failing examples this
# precedence chain is built to pass; they are reproduced verbatim in
# tests/test_parser_styles.py.

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)

_LETTER = re.compile(r"\b([A-L])\b", re.I)
# Fallback-only: excludes "I" -- as a bare word it is overwhelmingly the pronoun, not a
# choice letter, and this tier already means "no structured signal found, we're guessing."
# A genuine "I" answer is still caught upstream by the cue/marker/lone-line rules.
_LETTER_FALLBACK = re.compile(r"\b([A-HJ-L])\b", re.I)
_HASH_NUM = re.compile(r"####\s*(-?[\d,]+(?:\.\d+)?)")
_LAST_NUM = re.compile(r"(-?[\d,]+(?:\.\d+)?)")

_MC_ANSWER_CUE = re.compile(r"(?:final\s+answer|answer)\s*(?:is|:)\s*\(?([A-L])\)?", re.I)
_MC_BOXED = re.compile(r"\\boxed\{\s*\(?([A-L])\)?\s*\}", re.I)
_MC_BOLD = re.compile(r"\*\*\(?([A-L])\)?\*\*")
_MC_HASH = re.compile(r"####\s*\(?([A-L])\)?\b", re.I)
_MC_AFFIRM = re.compile(r"\b([A-L])\b\s*[?:]?\s*(?:is\s+)?(?:yes|correct|right)\b", re.I)
_MC_LONE_LINE = re.compile(r"(?m)^\s*\(?([A-L])\)?\.?\s*$", re.I)

_GSM_HASH = _HASH_NUM
_GSM_BOXED = re.compile(r"\\boxed\{\s*(-?[\d,]+(?:\.\d+)?)\s*\}")
_GSM_ANSWER_CUE = re.compile(r"(?:final\s+answer|answer)\s*(?:is|:)\s*\$?(-?[\d,]+(?:\.\d+)?)", re.I)


def _strip_reasoning(text: str) -> str:
    """Reasoning traces should never supply the answer. Servers normally split them into
    `reasoning_content` already (see client.py), but strip inline <think> blocks too in
    case a server or model inlines them into `content`."""
    return _THINK_BLOCK.sub("", text)


def _normalize_num(raw: str) -> str:
    """Strip thousands separators, any-length trailing decimal zeros (29.00 -> 29, not
    just 29.0), and leading zeros on the integer part, without corrupting a bare '0' or a
    non-numeric fallback string. Found via Phase 2 adjudication: the old .0-only strip let
    a correctly-extracted '29.00' miscompare against gold '29' and get scored wrong."""
    raw = raw.replace(",", "")
    if not raw.replace(".", "", 1).replace("-", "", 1).isdigit():
        return raw
    sign = "-" if raw.startswith("-") else ""
    body = raw[len(sign):]
    if "." in body:
        body = body.rstrip("0").rstrip(".")
    body = body.lstrip("0") or "0"
    return sign + body if body != "0" else "0"


def _loop_source_text(row: Mapping[str, Any]) -> str:
    return str(row.get("reasoning_content") or row.get("raw_text") or "")


def max_repeated_ngram(text: str, size: int = _LOOP_NGRAM) -> int:
    """How many times the most common word-n-gram appears. 1 means no repeats."""
    tokens = _LOOP_TOKEN.findall(text.lower())
    if len(tokens) < size:
        return 0
    counts: dict[str, int] = {}
    best = 0
    for index in range(len(tokens) - size + 1):
        gram = " ".join(tokens[index : index + size])
        counts[gram] = counts.get(gram, 0) + 1
        if counts[gram] > best:
            best = counts[gram]
    return best


def is_loop_failure(row: Mapping[str, Any]) -> bool:
    """True only for a failed item whose trace is a repeated phrase, not a long ramble."""
    if row.get("ok"):
        return False
    return max_repeated_ngram(_loop_source_text(row)) >= _LOOP_MIN_REPEATS


def category_score(rows: Iterable[Mapping[str, Any]]) -> float | None:
    rows = list(rows)
    if not rows:
        return None
    n_ok = sum(1 for r in rows if r.get("ok"))
    return 100.0 * n_ok / len(rows)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = pct * (len(s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def category_stats(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Phase 1 (sixcat v2.1): score plus the provenance a bare percentage hides —
    truncation and completion-token distribution, and (once Phase 2 lands) parser
    confidence. Additive to category_score; does not replace it.
    """
    rows = list(rows)
    n = len(rows)
    score = category_score(rows)
    truncated = sum(1 for r in rows if r.get("finish") == "length")
    loop_failures = sum(1 for r in rows if is_loop_failure(r))
    high_conf = sum(1 for r in rows if r.get("parse_confidence") == "high")
    low_conf = sum(1 for r in rows if r.get("parse_confidence") == "low")
    not_applicable = sum(1 for r in rows if r.get("parse_confidence") == "not_applicable")
    missing_conf = sum(1 for r in rows if r.get("parse_confidence") not in PARSE_CONFIDENCE_VALUES)
    ctoks = [r["ctok"] for r in rows if isinstance(r.get("ctok"), (int, float))]
    prefill = [float(r["prefill_tps"]) for r in rows if isinstance(r.get("prefill_tps"), (int, float))]
    decode = [float(r["decode_tps"]) for r in rows if isinstance(r.get("decode_tps"), (int, float))]
    speed = speed_from_rows(rows)
    return {
        "score": score,
        "n": n,
        "truncated": truncated,
        "loop_failures": loop_failures,
        "parse_high_confidence": high_conf,
        "parse_low_confidence": low_conf,
        "parse_confidence_not_applicable": not_applicable,
        "parse_confidence_missing": missing_conf,
        "ctok_p50": _percentile(ctoks, 0.50),
        "ctok_p95": _percentile(ctoks, 0.95),
        "ctok_max": max(ctoks) if ctoks else None,
        "speed_n": min(len(prefill), len(decode)),
        "prefill_tps_p50": _percentile(prefill, 0.50),
        "prefill_tps_p95": _percentile(prefill, 0.95),
        "decode_tps_p50": _percentile(decode, 0.50),
        "decode_tps_p95": _percentile(decode, 0.95),
        "tps_n": speed["items"],
        "tps_mean": speed["tps_mean"],
        "total_ctok": speed["total_ctok"],
        "total_wall_s": speed["total_wall_s"],
        "suite_tps": speed["suite_tps"],
    }


def speed_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Provider-agnostic completion tok/s from per-item wall clock."""
    pairs: list[tuple[float, float]] = []
    tps_vals: list[float] = []
    for row in rows:
        ctok = row.get("ctok")
        wall = row.get("wall_s")
        if not isinstance(ctok, (int, float)) or isinstance(ctok, bool):
            continue
        if not isinstance(wall, (int, float)) or isinstance(wall, bool) or wall <= 0:
            continue
        pairs.append((float(ctok), float(wall)))
        wall_tps = row.get("wall_tps")
        if isinstance(wall_tps, (int, float)) and not isinstance(wall_tps, bool):
            tps_vals.append(float(wall_tps))
        else:
            tps_vals.append(float(ctok) / float(wall))
    total_ctok = sum(ctok for ctok, _ in pairs)
    total_wall = sum(wall for _, wall in pairs)
    return {
        "items": len(tps_vals),
        "total_ctok": total_ctok,
        "total_wall_s": total_wall,
        "suite_tps": (total_ctok / total_wall) if total_wall else None,
        "tps_mean": (sum(tps_vals) / len(tps_vals)) if tps_vals else None,
    }


def suite_speed(packs: Mapping[str, Iterable[Mapping[str, Any]]]) -> dict[str, Any]:
    rows: list[Mapping[str, Any]] = []
    for items in packs.values():
        rows.extend(list(items))
    return speed_from_rows(rows)


def overall_score(cats: Mapping[str, float | None]) -> float:
    missing = [k for k in CATEGORIES if k not in cats]
    if missing:
        raise KeyError(f"missing categories: {missing}")
    vals = [cats[k] for k in CATEGORIES if cats[k] is not None]
    if not vals:
        raise ValueError("no category produced a score")
    return sum(vals) / len(vals)


def extract_mc_letter_conf(text: str) -> tuple[str | None, str]:
    """(letter, confidence). confidence='high' means a format/position rule fired;
    'low' means we fell all the way through to last-letter-in-text, the same guess the v1
    parser always made — kept as the final fallback, never the first choice."""
    if not text:
        return None, "low"
    text = _strip_reasoning(text)
    for pat in (_MC_ANSWER_CUE, _MC_BOXED, _MC_BOLD, _MC_HASH, _MC_AFFIRM, _MC_LONE_LINE):
        matches = pat.findall(text)
        if matches:
            return matches[-1].upper(), "high"
    letters = _LETTER_FALLBACK.findall(text)
    if not letters:
        return None, "low"
    return letters[-1].upper(), "low"


def extract_mc_letter(text: str) -> str | None:
    letter, _ = extract_mc_letter_conf(text)
    return letter


def extract_gsm_number_conf(text: str) -> tuple[str | None, str]:
    """(number, confidence) — see extract_mc_letter_conf for the confidence contract."""
    if not text:
        return None, "low"
    text = _strip_reasoning(text)
    for pat in (_GSM_HASH, _GSM_BOXED, _GSM_ANSWER_CUE):
        matches = pat.findall(text)
        if matches:
            return _normalize_num(matches[-1]), "high"
    found = _LAST_NUM.findall(text)
    if not found:
        return None, "low"
    return _normalize_num(found[-1]), "low"


def extract_gsm_number(text: str) -> str | None:
    number, _ = extract_gsm_number_conf(text)
    return number
