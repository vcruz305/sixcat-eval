from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _fake_completion(*args, **kwargs):
    return {
        "text": "    return 0\n",
        "reasoning_content": "",
        "tool_calls": [],
        "finish": "stop",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        "request_params": kwargs,
    }


def test_code_quick_uses_externally_ranked_hard_tasks():
    from sixcat.code import run_code

    items = [json.loads(line) for line in (ROOT / "sixcat/data/humaneval.jsonl").read_text(encoding="utf-8").splitlines()]

    class Client:
        complete = staticmethod(_fake_completion)

    with (
        patch("sixcat.code.read_jsonl", return_value=items),
        patch("sixcat.code._run_humaneval", return_value=True),
    ):
        rows = run_code(Client(), limit=3)

    assert [row["task_id"] for row in rows] == ["HumanEval/145", "HumanEval/132", "HumanEval/130"]


def test_code_full_uses_all_164_humaneval_tasks():
    from sixcat.code import run_code

    items = [json.loads(line) for line in (ROOT / "sixcat/data/humaneval.jsonl").read_text(encoding="utf-8").splitlines()]

    class Client:
        complete = staticmethod(_fake_completion)

    with (
        patch("sixcat.code.read_jsonl", return_value=items),
        patch("sixcat.code._run_humaneval", return_value=True),
    ):
        rows = run_code(Client(), limit=None)

    assert len(rows) == 164
    assert {row["task_id"] for row in rows} == {item["task_id"] for item in items}


def test_selection_profile_is_persisted_in_run_identity():
    from sixcat.__main__ import _journal_identity
    from sixcat.policy import strict_policy

    identity = _journal_identity(
        model="model-a",
        base_url="http://127.0.0.1:8083/v1",
        policy=strict_policy(),
        limit=20,
        request_timeout=180.0,
        skip_code_exec=False,
    )

    assert identity["selection_profile"] == "challenge-v1"
    assert len(identity["selection_fingerprint"]) == 12
