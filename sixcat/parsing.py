"""Parser-v5 answer extraction independent of the scoring aggregation layer."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?(?:</think\s*>|$)", re.S | re.I)
_LETTER_FALLBACK = re.compile(r"(?<![\w'’])([A-HJ-P])(?![\w'’])", re.I)
_NUM = r"[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?(?:\s*/\s*[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+))?"
_NUM_END = r"(?![\w,/+*^=-]|\.(?=\d))"
_HASH_NUM = re.compile(r"####\s*(" + _NUM + r")" + _NUM_END)
_LAST_NUM = re.compile(r"(?<![\w.])(" + _NUM + r")" + _NUM_END)
_MC_FINAL_CUE = re.compile(r"final\s+answer\s*(?:is|:)\s*\(?([A-P])\)?(?!\w)", re.I)
_MC_ANSWER_CUE = re.compile(r"(?:final\s+answer|answer)\s*(?:is|:)\s*\(?([A-P])\)?(?!\w)", re.I)
_MC_BOXED = re.compile(r"\\boxed\{\s*\(?([A-P])\)?\s*\}", re.I)
_MC_BOLD = re.compile(r"\*\*\(?([A-P])\)?\*\*")
_MC_HASH = re.compile(r"####\s*\(?([A-P])\)?\b", re.I)
_MC_AFFIRM = re.compile(r"\b([A-P])\b\s*[?:]?\s*(?:is\s+)?(?:yes|correct|right)\b", re.I)
_MC_LONE_LINE = re.compile(r"(?m)^\s*\(?([A-P])\)?\.?\s*$", re.I)
_GSM_HASH = _HASH_NUM
_GSM_BOXED = re.compile(r"\\boxed\{\s*(" + _NUM + r")\s*\}")
_GSM_ANSWER_CUE = re.compile(r"(?:final\s+answer|answer)\s*(?:is|:)\s*\$?(" + _NUM + r")" + _NUM_END, re.I)


def strip_reasoning(text: str) -> str:
    return _THINK_BLOCK.sub("", text)


def normalize_num(raw: str) -> str:
    """Canonical exact number, including finite decimals, exponents and fractions."""
    clean = raw.strip()
    if len(clean) > 256:
        raise ValueError("numeric expression too long")
    for part in clean.split("/"):
        part = part.strip()
        if "," in part and not re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", part):
            raise ValueError("malformed thousands grouping")
    clean = clean.replace(",", "")
    for exponent in re.findall(r"[eE]([+-]?\d+)", clean):
        if abs(int(exponent)) > 1000:
            raise ValueError("numeric exponent too large")
    parts = clean.split("/")
    if len(parts) > 2:
        raise ValueError("unsupported numeric expression")
    value = Fraction(Decimal(parts[0].strip()))
    if len(parts) == 2:
        value /= Fraction(Decimal(parts[1].strip()))
    if value.denominator == 1:
        return str(value.numerator)
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        return f"{value.numerator}/{value.denominator}"
    places = max(twos, fives)
    scaled = abs(value.numerator) * 2 ** (places - twos) * 5 ** (places - fives)
    digits = str(scaled).zfill(places + 1)
    result = digits[:-places] + "." + digits[-places:]
    return ("-" if value < 0 else "") + result.rstrip("0").rstrip(".")


def parse_mc_answer(text: str, valid_letters: str | None = None) -> dict[str, Any]:
    text = strip_reasoning(text or "")
    for pattern in (_MC_FINAL_CUE, _MC_ANSWER_CUE, _MC_BOXED, _MC_BOLD, _MC_HASH, _MC_AFFIRM, _MC_LONE_LINE):
        matches = [value.upper() for value in pattern.findall(text)]
        if not matches:
            continue
        if len(set(matches)) > 1:
            return {"value": None, "confidence": "low", "status": "ambiguous"}
        value = matches[-1]
        if valid_letters is not None and value not in valid_letters:
            return {"value": None, "confidence": "low", "status": "out_of_range"}
        return {"value": value, "confidence": "high", "status": "parsed"}
    letters = [value.upper() for value in _LETTER_FALLBACK.findall(text)]
    if len(set(letters)) > 1:
        return {"value": None, "confidence": "low", "status": "ambiguous"}
    value = letters[-1] if letters else None
    if valid_letters is not None and value not in valid_letters:
        value = None
    return {"value": value, "confidence": "low", "status": "fallback" if value else "unparsed"}


def parse_gsm_answer(text: str) -> dict[str, Any]:
    text = strip_reasoning(text or "")
    for pattern in (_GSM_HASH, _GSM_BOXED, _GSM_ANSWER_CUE):
        matches = pattern.findall(text)
        if matches:
            try:
                value = normalize_num(matches[-1])
            except (ValueError, InvalidOperation, ZeroDivisionError, OverflowError):
                return {"value": None, "confidence": "low", "status": "unsupported_format"}
            return {"value": value, "confidence": "high", "status": "parsed"}
    if "####" in text or "\\boxed{" in text:
        return {"value": None, "confidence": "low", "status": "unsupported_format"}
    matches = _LAST_NUM.findall(text)
    try:
        value = normalize_num(matches[-1]) if matches else None
    except (ValueError, InvalidOperation, ZeroDivisionError, OverflowError):
        value = None
    return {"value": value, "confidence": "low", "status": "fallback" if value else "unparsed"}
