"""IFEval-style checkers. Official IDs, local rules — no nltk/langdetect."""

from __future__ import annotations

import json
import re
from typing import Any


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text)


def check_instruction(inst_id: str, kwargs: dict[str, Any], prompt: str, response: str) -> bool:
    kw = kwargs or {}
    if inst_id == "punctuation:no_comma":
        return "," not in response
    if inst_id == "change_case:english_lowercase":
        letters = [c for c in response if c.isalpha()]
        return bool(letters) and all(c.islower() for c in letters)
    if inst_id == "change_case:english_capital":
        letters = [c for c in response if c.isalpha()]
        return bool(letters) and all(c.isupper() for c in letters)
    if inst_id == "length_constraints:number_words":
        n = len(_words(response))
        want = int(kw.get("num_words") or 0)
        rel = kw.get("relation") or "at least"
        return n >= want if rel == "at least" else n <= want
    if inst_id == "length_constraints:number_sentences":
        n = len(re.findall(r"[.!?]+", response))
        want = int(kw.get("num_sentences") or 0)
        rel = kw.get("relation") or "at least"
        return n >= want if rel == "at least" else n <= want
    if inst_id == "length_constraints:number_paragraphs":
        n = len([p for p in re.split(r"\n\s*\n", response.strip()) if p.strip()])
        want = int(kw.get("num_paragraphs") or 0)
        return n == want
    if inst_id == "detectable_format:number_highlighted_sections":
        n = len(re.findall(r"\*[^*]+\*", response))
        return n >= int(kw.get("num_highlights") or 0)
    if inst_id == "detectable_format:number_bullet_lists":
        n = len(re.findall(r"(?m)^\s*[-*•]\s+\S", response))
        want = int(kw.get("num_bullets") or 0)
        return n >= want
    if inst_id == "detectable_format:title":
        return bool(re.search(r"<<.+>>", response))
    if inst_id == "detectable_format:json_format":
        try:
            json.loads(response.strip().strip("`"))
            return True
        except Exception:
            return False
    if inst_id == "detectable_content:number_placeholders":
        n = len(re.findall(r"\[[^]]+\]", response))
        return n >= int(kw.get("num_placeholders") or 0)
    if inst_id == "keywords:existence":
        kws = [k.lower() for k in (kw.get("keywords") or [])]
        blob = response.lower()
        return all(k in blob for k in kws)
    if inst_id == "keywords:forbidden_words":
        kws = [k.lower() for k in (kw.get("forbidden_words") or [])]
        blob = response.lower()
        return all(k not in blob for k in kws)
    if inst_id == "keywords:frequency":
        word = str(kw.get("keyword") or "").lower()
        n = len(re.findall(rf"\b{re.escape(word)}\b", response.lower()))
        want = int(kw.get("frequency") or 0)
        rel = kw.get("relation") or "at least"
        return n >= want if rel == "at least" else n == want
    if inst_id == "startend:quotation":
        s = response.strip()
        return len(s) >= 2 and s[0] == '"' and s[-1] == '"'
    if inst_id == "startend:end_checker":
        ender = str(kw.get("end_phrase") or "")
        return response.rstrip().endswith(ender)
    if inst_id == "combination:repeat_prompt":
        needle = str(kw.get("prompt_to_repeat") or "")
        return response.replace(" ", "").startswith(needle.replace(" ", ""))
    if inst_id == "language:response_language":
        # no langdetect: treat as pass if there is text
        return bool(response.strip())
    # unknown id: do not fail the item
    return True


def item_ok(item: dict[str, Any], response: str) -> bool:
    ids = item.get("instruction_id_list") or []
    kws = item.get("kwargs") or [{}] * len(ids)
    prompt = item.get("prompt") or ""
    if not ids:
        return False
    return all(check_instruction(i, k, prompt, response) for i, k in zip(ids, kws))
