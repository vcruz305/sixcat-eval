"""Deterministic local checkers for every instruction shipped in IFEval-100."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

SUPPORTED_INSTRUCTION_IDS = frozenset(
    {
        "change_case:capital_word_frequency",
        "change_case:english_capital",
        "change_case:english_lowercase",
        "combination:repeat_prompt",
        "combination:two_responses",
        "detectable_content:number_placeholders",
        "detectable_content:postscript",
        "detectable_format:json_format",
        "detectable_format:multiple_sections",
        "detectable_format:number_bullet_lists",
        "detectable_format:number_highlighted_sections",
        "detectable_format:title",
        "keywords:existence",
        "keywords:forbidden_words",
        "keywords:frequency",
        "keywords:letter_frequency",
        "language:response_language",
        "length_constraints:number_paragraphs",
        "length_constraints:number_sentences",
        "length_constraints:number_words",
        "punctuation:no_comma",
        "startend:end_checker",
        "startend:quotation",
    }
)


def _words(text: str) -> list[str]:
    return re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)


def _relation(actual: int, threshold: int, relation: str) -> bool:
    if relation == "less than":
        return actual < threshold
    if relation == "at least":
        return actual >= threshold
    return False


def _sentence_count(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return len([part for part in re.split(r"[.!?]+(?:\s+|$)", stripped) if part.strip()])


def _language_is(response: str, expected: str) -> bool:
    if not response.strip() or not expected:
        return False
    try:
        return detect(response) == expected
    except LangDetectException:
        return False


def _paragraph_count_ok(response: str, expected: int) -> bool:
    paragraphs = re.split(r"\s?\*\*\*\s?", response)
    count = len(paragraphs)
    for index, paragraph in enumerate(paragraphs):
        if paragraph.strip():
            continue
        if index in (0, len(paragraphs) - 1):
            count -= 1
        else:
            return False
    return count == expected


def _highlight_count(response: str) -> int:
    pattern = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+)(?<!\*)\*(?!\*)|\*\*([^*\n]+)\*\*")
    return sum(1 for match in pattern.finditer(response) if any((group or "").strip() for group in match.groups()))


def _two_responses_ok(response: str) -> bool:
    valid: list[str] = []
    parts = response.split("******")
    for index, part in enumerate(parts):
        if part.strip():
            valid.append(part.strip())
        elif index not in (0, len(parts) - 1):
            return False
    return len(valid) == 2 and valid[0] != valid[1]


def check_instruction(inst_id: str, kwargs: dict[str, Any], prompt: str, response: str) -> bool:
    """Return False for unsupported or malformed constraints; scoring never fails open."""
    del prompt
    if inst_id not in SUPPORTED_INSTRUCTION_IDS or not isinstance(kwargs, dict):
        return False
    kw = kwargs
    try:
        if inst_id == "punctuation:no_comma":
            return "," not in response
        if inst_id == "change_case:english_lowercase":
            return response.islower() and _language_is(response, "en")
        if inst_id == "change_case:english_capital":
            return response.isupper() and _language_is(response, "en")
        if inst_id == "change_case:capital_word_frequency":
            words = re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", response)
            actual = sum(1 for word in words if word.isupper())
            return _relation(actual, int(kw["capital_frequency"]), str(kw["capital_relation"]))
        if inst_id == "length_constraints:number_words":
            return _relation(len(_words(response)), int(kw["num_words"]), str(kw["relation"]))
        if inst_id == "length_constraints:number_sentences":
            return _relation(_sentence_count(response), int(kw["num_sentences"]), str(kw["relation"]))
        if inst_id == "length_constraints:number_paragraphs":
            return _paragraph_count_ok(response, int(kw["num_paragraphs"]))
        if inst_id == "detectable_format:number_highlighted_sections":
            return _highlight_count(response) >= int(kw["num_highlights"])
        if inst_id == "detectable_format:number_bullet_lists":
            stars = re.findall(r"^\s*\*[^*].*$", response, flags=re.MULTILINE)
            dashes = re.findall(r"^\s*-.*$", response, flags=re.MULTILINE)
            return len(stars) + len(dashes) == int(kw["num_bullets"])
        if inst_id == "detectable_format:title":
            return any(title.strip("<>").strip() for title in re.findall(r"<<[^\n]+>>", response))
        if inst_id == "detectable_format:json_format":
            value = re.sub(r"^```(?:json)?\s*", "", response.strip(), flags=re.IGNORECASE)
            value = re.sub(r"\s*```$", "", value).strip()
            json.loads(value)
            return True
        if inst_id == "detectable_format:multiple_sections":
            splitter = str(kw["section_spliter"]).strip()
            pattern = r"\s?" + re.escape(splitter) + r"\s?\d+\s?"
            return len(re.split(pattern, response)) - 1 >= int(kw["num_sections"])
        if inst_id == "detectable_content:number_placeholders":
            return len(re.findall(r"\[.*?\]", response)) >= int(kw["num_placeholders"])
        if inst_id == "detectable_content:postscript":
            marker = str(kw["postscript_marker"]).strip()
            if marker == "P.P.S":
                pattern = r"\s*p\.\s?p\.\s?s.*$"
            elif marker == "P.S.":
                pattern = r"\s*p\.\s?s\..*$"
            else:
                pattern = r"\s*" + re.escape(marker.lower()) + r".*$"
            return bool(re.findall(pattern, response.lower(), flags=re.MULTILINE))
        if inst_id == "keywords:existence":
            return all(re.search(re.escape(str(word)), response, flags=re.IGNORECASE) for word in kw["keywords"])
        if inst_id == "keywords:forbidden_words":
            return all(
                not re.search(re.escape(str(word)), response, flags=re.IGNORECASE)
                for word in kw["forbidden_words"]
            )
        if inst_id == "keywords:frequency":
            actual = len(re.findall(re.escape(str(kw["keyword"])), response, flags=re.IGNORECASE))
            return _relation(actual, int(kw["frequency"]), str(kw["relation"]))
        if inst_id == "keywords:letter_frequency":
            letter = str(kw["letter"]).lower()
            actual = Counter(response.lower())[letter]
            return _relation(actual, int(kw["let_frequency"]), str(kw["let_relation"]))
        if inst_id == "startend:quotation":
            value = response.strip()
            return len(value) > 1 and value[0] == '"' and value[-1] == '"'
        if inst_id == "startend:end_checker":
            ender = str(kw["end_phrase"]).strip().casefold()
            return response.strip().strip('"').casefold().endswith(ender)
        if inst_id == "combination:repeat_prompt":
            needle = str(kw["prompt_to_repeat"]).strip().casefold()
            return bool(needle) and response.strip().casefold().startswith(needle)
        if inst_id == "combination:two_responses":
            return _two_responses_ok(response)
        if inst_id == "language:response_language":
            return _language_is(response, str(kw["language"]))
    except (KeyError, TypeError, ValueError, re.error):
        return False
    return False


def item_ok(item: dict[str, Any], response: str) -> bool:
    ids = item.get("instruction_id_list") or []
    kwargs = item.get("kwargs") or []
    prompt = item.get("prompt") or ""
    if not response.strip() or not ids or len(ids) != len(kwargs):
        return False
    return all(check_instruction(inst_id, kw, prompt, response) for inst_id, kw in zip(ids, kwargs))
