"""challenge-v2 Instruct: stacked, deterministic output constraints.

v1 Instruct uses IFEval items with one to three constraints drawn from a
small, heavily trained-on set. v2 items stack four to six checks per prompt
(the two JSON items bundle theirs into one typed-shape check) and add structural checks IFEval does not have (per-line word counts,
acrostics, exact word totals, unique words, typed JSON shapes, number sums).

Every `v2:` checker is pure Python with no language detection, so a verdict
cannot change with a library version. v1 checkers are reused through
`sixcat.instruct.check_instruction` for constraints they already cover.
Unknown ids and malformed arguments fail closed, as in v1.

Definitions used by the prompts and by the checkers:

* line       a line of the response that is not blank
* word       a whitespace-separated token containing at least one letter or digit
* paragraph  a block of text separated from the next by at least one blank line

If the whole response is wrapped in one Markdown code fence, the fence lines
are ignored.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .instruct import check_instruction

V2_INSTRUCTION_IDS = frozenset({
    "v2:acrostic", "v2:alliteration", "v2:alphabetical_lines", "v2:alternating_prefixes",
    "v2:char_count", "v2:char_occurrences", "v2:forbidden_chars", "v2:integers_sum",
    "v2:json_object", "v2:line_count", "v2:line_endings", "v2:line_regex", "v2:line_starts",
    "v2:max_word_length", "v2:no_lowercase", "v2:no_uppercase", "v2:nth_word", "v2:paragraphs",
    "v2:required_order", "v2:starts_with", "v2:unique_words", "v2:word_count", "v2:word_ladder",
    "v2:words_per_line",
})

_FENCE = re.compile(r"^```[\w-]*\s*$")


def unfence(response: str) -> str:
    text = response.strip()
    rows = text.splitlines()
    if len(rows) >= 2 and _FENCE.match(rows[0].strip()) and rows[-1].strip() == "```":
        return "\n".join(rows[1:-1]).strip()
    return text


def lines_of(text: str) -> list[str]:
    return [row.strip() for row in text.splitlines() if row.strip()]


def words_of(text: str) -> list[str]:
    return [token for token in text.split() if any(ch.isalnum() for ch in token)]


def bare(word: str) -> str:
    """A word without surrounding punctuation, case-folded."""
    start, end = 0, len(word)
    while start < end and not word[start].isalnum():
        start += 1
    while end > start and not word[end - 1].isalnum():
        end -= 1
    return word[start:end].casefold()


def _relation(actual: int, relation: str, expected: int) -> bool:
    if relation == "exactly":
        return actual == expected
    if relation == "at least":
        return actual >= expected
    if relation == "at most":
        return actual <= expected
    return False


def _json_value_ok(value: Any, spec: dict[str, Any]) -> bool:
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str) or not value.strip():
            return False
        if "max_words" in spec and len(words_of(value)) > int(spec["max_words"]):
            return False
        return "enum" not in spec or value in spec["enum"]
    if kind == "integer":
        if type(value) is not int:
            return False
        return int(spec.get("min", value)) <= value <= int(spec.get("max", value))
    if kind == "boolean":
        return type(value) is bool
    if kind == "array":
        if not isinstance(value, list):
            return False
        if "length" in spec and len(value) != int(spec["length"]):
            return False
        item_spec = spec.get("items")
        if item_spec is not None and not all(_json_value_ok(item, item_spec) for item in value):
            return False
        if spec.get("sorted") and [str(v).casefold() for v in value] != sorted(str(v).casefold() for v in value):
            return False
        return True
    return False


def check_v2(inst_id: str, kwargs: dict[str, Any], response: str) -> bool:
    if inst_id not in V2_INSTRUCTION_IDS or not isinstance(kwargs, dict):
        return False
    kw = kwargs
    text = unfence(response)
    lines = lines_of(text)
    try:
        if inst_id == "v2:line_count":
            return _relation(len(lines), str(kw["relation"]), int(kw["n"]))
        if inst_id == "v2:words_per_line":
            return bool(lines) and all(
                _relation(len(words_of(line)), str(kw["relation"]), int(kw["n"])) for line in lines)
        if inst_id == "v2:word_ladder":
            start, step = int(kw["start"]), int(kw["step"])
            return bool(lines) and all(
                len(words_of(line)) == start + index * step for index, line in enumerate(lines))
        if inst_id == "v2:word_count":
            return _relation(len(words_of(text)), str(kw["relation"]), int(kw["n"]))
        if inst_id == "v2:char_count":
            return _relation(len(text), str(kw["relation"]), int(kw["n"]))
        if inst_id == "v2:char_occurrences":
            return text.count(str(kw["char"])) == int(kw["n"])
        if inst_id == "v2:forbidden_chars":
            return bool(text) and not any(ch in text for ch in str(kw["chars"]))
        if inst_id == "v2:no_uppercase":
            return any(ch.isalpha() for ch in text) and not any(ch.isupper() for ch in text)
        if inst_id == "v2:no_lowercase":
            return any(ch.isalpha() for ch in text) and not any(ch.islower() for ch in text)
        if inst_id == "v2:acrostic":
            target = str(kw["word"]).casefold()
            initials = []
            for line in lines:
                letters = [ch for ch in line if ch.isalpha()]
                if not letters:
                    return False
                initials.append(letters[0].casefold())
            return bool(target) and "".join(initials) == target
        if inst_id == "v2:alliteration":
            words = [bare(word) for word in words_of(text)]
            return bool(words) and all(word.startswith(str(kw["letter"]).casefold()) for word in words)
        if inst_id == "v2:unique_words":
            words = [bare(word) for word in words_of(text)]
            return bool(words) and len(words) == len(set(words))
        if inst_id == "v2:max_word_length":
            words = [bare(word) for word in words_of(text)]
            limit = int(kw["n"])
            return bool(words) and all(sum(ch.isalnum() for ch in word) <= limit for word in words)
        if inst_id == "v2:nth_word":
            words = [bare(word) for word in words_of(text)]
            index = int(kw["n"]) - 1
            return 0 <= index < len(words) and words[index] == str(kw["word"]).casefold()
        if inst_id == "v2:line_endings":
            return bool(lines) and all(line.endswith(str(kw["suffix"])) for line in lines)
        if inst_id == "v2:line_starts":
            return bool(lines) and all(line.startswith(str(kw["prefix"])) for line in lines)
        if inst_id == "v2:alternating_prefixes":
            prefixes = [str(prefix) for prefix in kw["prefixes"]]
            return bool(lines) and bool(prefixes) and all(
                line.startswith(prefixes[index % len(prefixes)]) for index, line in enumerate(lines))
        if inst_id == "v2:line_regex":
            pattern = re.compile(str(kw["pattern"]))
            return bool(lines) and all(pattern.fullmatch(line) for line in lines)
        if inst_id == "v2:alphabetical_lines":
            firsts = []
            for line in lines:
                words = words_of(line)
                if not words:
                    return False
                firsts.append(bare(words[0]))
            return len(firsts) >= 2 and all(a < b for a, b in zip(firsts, firsts[1:]))
        if inst_id == "v2:starts_with":
            return text.startswith(str(kw["text"]))
        if inst_id == "v2:paragraphs":
            blocks = [block for block in re.split(r"\n[ \t]*\n", text) if block.strip()]
            return len(blocks) == int(kw["n"])
        if inst_id == "v2:required_order":
            lowered = text.casefold()
            positions = [lowered.find(str(term).casefold()) for term in kw["terms"]]
            return bool(positions) and all(p >= 0 for p in positions) and positions == sorted(positions) \
                and len(set(positions)) == len(positions)
        if inst_id == "v2:integers_sum":
            numbers = [int(match) for match in re.findall(r"\d+", text)]
            return len(numbers) == int(kw["count"]) and sum(numbers) == int(kw["total"])
        if inst_id == "v2:json_object":
            value = json.loads(text)
            fields = kw["fields"]
            if not isinstance(value, dict) or set(value) != set(fields):
                return False
            return all(_json_value_ok(value[name], spec) for name, spec in fields.items())
    except (KeyError, TypeError, ValueError, re.error):
        return False
    return False


def check_any(inst_id: str, kwargs: dict[str, Any], prompt: str, response: str) -> bool:
    if isinstance(inst_id, str) and inst_id.startswith("v2:"):
        return check_v2(inst_id, kwargs, response)
    return check_instruction(inst_id, kwargs, prompt, response)


def item_ok_v2(item: dict[str, Any], response: str) -> bool:
    ids = item.get("instruction_id_list") or []
    kwargs = item.get("kwargs") or []
    prompt = item.get("prompt") or ""
    if not response.strip() or not ids or len(ids) != len(kwargs):
        return False
    return all(check_any(inst_id, kw, prompt, response) for inst_id, kw in zip(ids, kwargs))


def failed_constraints(item: dict[str, Any], response: str) -> list[str]:
    """Constraint ids that did not pass, for receipts and debugging."""
    ids = item.get("instruction_id_list") or []
    kwargs = item.get("kwargs") or []
    prompt = item.get("prompt") or ""
    if len(ids) != len(kwargs):
        return list(ids)
    return [inst_id for inst_id, kw in zip(ids, kwargs)
            if not response.strip() or not check_any(inst_id, kw, prompt, response)]
