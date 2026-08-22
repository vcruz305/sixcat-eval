from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Sequence


SELECTION_PROFILE = "challenge-v1"

# HumanEval item pass rates across a 49-model panel, hardest first:
# https://ai.rhiza.fr/humaneval/tasks.html
CODE_CHALLENGE_IDS = (
    "HumanEval/145", "HumanEval/132", "HumanEval/130", "HumanEval/32",
    "HumanEval/127", "HumanEval/134", "HumanEval/108", "HumanEval/93",
    "HumanEval/83", "HumanEval/65", "HumanEval/129", "HumanEval/91",
    "HumanEval/115", "HumanEval/120", "HumanEval/125", "HumanEval/126",
    "HumanEval/140", "HumanEval/54", "HumanEval/160", "HumanEval/118",
)

# Frozen from cross-model Sixcat receipts (12-21 attempts/item), hardest first.
KNOWLEDGE_CHALLENGE_INDICES = {
    "mmlu": (18, 8, 7, 4, 2),
    "arc": (13, 7, 0, 1, 2),
    "winogrande": (13, 15, 1, 6, 12),
    "hellaswag": (10, 16, 14, 1, 17),
}
MATH_CHALLENGE_INDICES = (18, 9, 0, 12, 1, 2, 3, 4, 10, 11, 13, 14, 15, 16, 17, 19, 5, 6, 7, 8)
TRUTH_CHALLENGE_INDICES = (17, 19, 7, 1, 15, 0, 3, 2, 4, 10, 11, 12, 13, 14, 16, 18, 5, 6, 8, 9)

# Static constraint-density ranking over the shipped IFEval-100 corpus.
INSTRUCT_CHALLENGE_INDICES = (66, 39, 74, 33, 7, 67, 81, 0, 59, 9, 77, 80, 89, 72, 54, 82, 79, 62, 57, 93)

_SELECTION_PAYLOAD = {
    "profile": SELECTION_PROFILE,
    "code": CODE_CHALLENGE_IDS,
    "knowledge": KNOWLEDGE_CHALLENGE_INDICES,
    "math": MATH_CHALLENGE_INDICES,
    "truth": TRUTH_CHALLENGE_INDICES,
    "instruct": INSTRUCT_CHALLENGE_INDICES,
    "tools": "exact-arguments-and-multicall-v1",
}
SELECTION_FINGERPRINT = hashlib.sha256(
    json.dumps(_SELECTION_PAYLOAD, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()[:12]


def select_by_indices(items: Sequence[Any], limit: int | None, preferred: Sequence[int]) -> list[Any]:
    """Return full source order for full mode, otherwise frozen challenge order."""
    return [item for _, item in select_indexed_by_indices(items, limit, preferred)]


def select_indexed_by_indices(
    items: Sequence[Any], limit: int | None, preferred: Sequence[int]
) -> list[tuple[int, Any]]:
    """Like select_by_indices, while preserving source indices for receipt keys."""
    source = list(items)
    if limit is None:
        return list(enumerate(source))
    seen: set[int] = set()
    order = []
    for index in (*preferred, *range(len(source))):
        if 0 <= index < len(source) and index not in seen:
            seen.add(index)
            order.append(index)
    return [(index, source[index]) for index in order[:limit]]


def select_by_ids(
    items: Sequence[Any],
    limit: int | None,
    preferred: Sequence[str],
    *,
    key: Callable[[Any], str],
) -> list[Any]:
    source = list(items)
    if limit is None:
        return source
    by_id = {key(item): item for item in source}
    selected = [by_id[item_id] for item_id in preferred if item_id in by_id]
    selected_ids = {key(item) for item in selected}
    selected.extend(item for item in source if key(item) not in selected_ids)
    return selected[:limit]
