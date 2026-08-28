"""Lint invariants for the shipped benchmark data.

These catch sixcat-side construction bugs only. Items whose quirks are
inherited from the upstream anchor sets (tinyBenchmarks, google/IFEval) are
deliberately NOT edited here: receipts stay comparable to the upstream anchors.
Known upstream quirks are listed in docs/eval-run-findings.md.
"""
import json
from pathlib import Path

import pytest

from sixcat import dataio

DATA_DIR = Path(dataio.__file__).resolve().parent / "data"


def _rows(name):
    return [json.loads(line) for line in (DATA_DIR / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def _index_key(item, key, n_choices, name, i):
    key = int(key)
    assert 0 <= key < n_choices, f"{name}[{i}] answer index {key!r} outside {n_choices} choices"


def test_mmlu_answer_key_is_within_choices():
    for i, item in enumerate(_rows("tiny_mmlu.jsonl")):
        _index_key(item, item["answer"], len(item["choices"]), "tiny_mmlu", i)


def test_arc_answer_aligns_with_labels_and_texts():
    from sixcat.run import arc_answer_letter

    for i, item in enumerate(_rows("tiny_arc.jsonl")):
        texts = item.get("texts") or []
        labels = item.get("labels") or []
        assert len(labels) == len(texts), f"tiny_arc[{i}] labels/texts mismatch"
        assert str(item["answer"]) in labels, f"tiny_arc[{i}] answer {item['answer']!r} not in labels"
        assert arc_answer_letter(item) in "ABCD", f"tiny_arc[{i}] unmappable answer"


def test_hellaswag_answer_is_within_endings():
    for i, item in enumerate(_rows("tiny_hellaswag.jsonl")):
        _index_key(item, item["answer"], len(item["endings"]), "tiny_hellaswag", i)


def test_winogrande_answer_names_one_option():
    for i, item in enumerate(_rows("tiny_winogrande.jsonl")):
        assert str(item["answer"]) in {"1", "2"}, f"tiny_winogrande[{i}] bad answer {item['answer']!r}"


def test_truthfulqa_answer_is_within_choices():
    for i, item in enumerate(_rows("tiny_truthfulqa.jsonl")):
        _index_key(item, item["answer"], len(item["choices"]), "tiny_truthfulqa", i)


def test_gsm8k_answers_carry_final_number():
    from sixcat.score import extract_gsm_number

    for i, item in enumerate(_rows("tiny_gsm8k.jsonl")):
        assert extract_gsm_number(item["answer"]) is not None, f"tiny_gsm8k[{i}] has no #### number"


def test_ifeval_instruction_ids_are_all_supported():
    # sixcat's contract is "unknown IDs fail closed"; this lint catches a
    # shipped item silently zeroing because its id was never implemented.
    from sixcat.instruct import SUPPORTED_INSTRUCTION_IDS

    for i, item in enumerate(_rows("ifeval_100.jsonl")):
        ids = item.get("instruction_id_list") or []
        assert ids, f"ifeval_100[{i}] ({item.get('key')}) has no instruction ids"
        for inst_id in ids:
            assert inst_id in SUPPORTED_INSTRUCTION_IDS, (
                f"ifeval_100[{i}] ({item.get('key')}) uses unsupported instruction id {inst_id!r}"
            )


def test_ifeval_kwargs_align_with_instruction_ids():
    for i, item in enumerate(_rows("ifeval_100.jsonl")):
        kwargs = item.get("kwargs") or []
        ids = item.get("instruction_id_list") or []
        assert len(kwargs) == len(ids), (
            f"ifeval_100[{i}] ({item.get('key')}) kwargs/instruction_id_list length mismatch"
        )


def test_tools_expectations_shape():
    from sixcat.tools import ITEMS

    for name, want, prompt in ITEMS:
        assert want is None or isinstance(want, (str, list)), f"tools item {name!r} bad expectation type"
        if isinstance(want, list):
            for entry in want:
                assert isinstance(entry, tuple) and len(entry) == 2, f"tools item {name!r} bad call entry"


def test_selection_indices_reference_live_rows():
    from sixcat.selection import (
        INSTRUCT_CHALLENGE_INDICES,
        KNOWLEDGE_CHALLENGE_INDICES,
        MATH_CHALLENGE_INDICES,
        TRUTH_CHALLENGE_INDICES,
    )

    checks = [
        (KNOWLEDGE_CHALLENGE_INDICES["mmlu"], "tiny_mmlu.jsonl"),
        (KNOWLEDGE_CHALLENGE_INDICES["arc"], "tiny_arc.jsonl"),
        (KNOWLEDGE_CHALLENGE_INDICES["hellaswag"], "tiny_hellaswag.jsonl"),
        (KNOWLEDGE_CHALLENGE_INDICES["winogrande"], "tiny_winogrande.jsonl"),
        (MATH_CHALLENGE_INDICES, "tiny_gsm8k.jsonl"),
        (TRUTH_CHALLENGE_INDICES, "tiny_truthfulqa.jsonl"),
        (INSTRUCT_CHALLENGE_INDICES, "ifeval_100.jsonl"),
    ]
    for indices, name in checks:
        n = len(_rows(name))
        for idx in indices:
            assert 0 <= idx < n, f"{name}: challenge index {idx} out of range ({n} rows)"
