"""One completion receipt format for every category."""
from __future__ import annotations
import copy
from typing import Any
from .score import answer_tokens, is_loop_failure

def completion_row(out: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Phase 1 (sixcat v2.1): every emitted row carries finish/ctok/request_params so
    truncation and budget questions are answerable from the JSONL after the fact.
    """
    usage = out.get("usage") or {}
    row: dict[str, Any] = dict(extra)
    row["finish"] = out.get("finish")
    row["ctok"] = usage.get("completion_tokens")
    row["ptok"] = usage.get("prompt_tokens")
    rtok = usage.get("reasoning_tokens")
    if rtok is None:
        rtok = out.get("reasoning_tokens")
    row["rtok"] = rtok
    row["atok"] = answer_tokens(row.get("ctok"), rtok)
    row["request_params"] = out.get("request_params")
    if "parse_confidence" in out:
        row["parse_confidence"] = out["parse_confidence"]
    if "raw_text" in out:
        row["raw_text"] = out["raw_text"]
    elif "text" in out:
        row["raw_text"] = out["text"] or ""
    if "reasoning_content" in out:
        row["reasoning_content"] = out["reasoning_content"]
    for key in (
        "prefill_tps",
        "decode_tps",
        "prefill_ms",
        "decode_ms",
        "prefill_n",
        "decode_n",
        "speed_source",
        "wall_s",
        "wall_tps",
    ):
        if key in out:
            row[key] = out[key]
    if row.get("wall_tps") is None:
        ctok = row.get("ctok")
        wall = row.get("wall_s")
        if (
            isinstance(ctok, (int, float))
            and not isinstance(ctok, bool)
            and isinstance(wall, (int, float))
            and not isinstance(wall, bool)
            and wall > 0
        ):
            row["wall_tps"] = float(ctok) / float(wall)
    for key in ("prompt", "wire_request", "provider_model", "system_fingerprint", "parse_status", "source_text", "generation_reused"):
        if key in out:
            row[key] = copy.deepcopy(out[key])
    row["status"] = "response"
    row["scored"] = True
    row["loop"] = is_loop_failure(row)
    return row
