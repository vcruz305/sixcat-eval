"""Default Hermes scope: all 120 items, with real local HumanEval execution.

The provider below is an offline fixture, not a live model or a model score.
Only provider/auth are mocked; HTTP, scheduling, grading and Python execution
use the real implementation. No container, GPU or external provider is needed.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sixcat import hermes
from sixcat.dataio import read_jsonl
from sixcat.score import CATEGORIES
from sixcat.tools import ITEMS


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DOCS = [
    "docs/hermes.md",
    "docs/hermes-nous.md",
    ".hermes/skills/sixcat-eval/SKILL.md",
    "AGENTS.md",
]


@pytest.mark.parametrize("name", ACTIVE_DOCS)
def test_operator_docs_default_to_120_and_local_code(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert "Code execution is enabled by default" in flat
    assert "120 items" in flat
    assert "locally" in flat
    assert "explicitly" in flat and "--skip-code-exec" in flat
    for old in ("already-approved isolated", "missing required isolation",
                "`--skip-code-exec` automatically", "code-isolation and incomplete-result"):
        assert old not in flat


@pytest.mark.parametrize("name", ["docs/hermes.md", "docs/hermes-nous.md"])
def test_copyable_run_commands_do_not_disable_code(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    blocks = re.findall(r"```(?:bash|text)\n(.*?)```", text, re.DOTALL)
    commands = [block for block in blocks if "sixcat.hermes run" in block]
    assert commands, "Keep a copyable standard command in each guide"
    for block in commands:
        assert "--skip-code-exec" not in block
    # Also prevent reintroducing the old expanded controller prompt.
    assert "This is a 100-item, five-category run" not in text


@pytest.mark.parametrize("skip_code", [False, True], ids=["default-120-with-code", "explicit-opt-out-100"])
def test_hermes_cli_standard_scope_executes_local_code(monkeypatch, tmp_path, skip_code):
    target = hermes.HermesRuntimeTarget(
        profile="fixture", model="fixture-model", provider="nous",
        runtime={"api_key": "fixture-not-a-live-key", "base_url": "https://example.invalid/v1",
                 "api_mode": "chat_completions"},
    )
    monkeypatch.setattr(hermes, "resolve_runtime_target", lambda **kwargs: target)
    code_answers = {
        "Complete the following Python function. Output only code.\n\n" + item["prompt"]:
            item["canonical_solution"] for item in read_jsonl("humaneval.jsonl")
    }
    tool_answers = {prompt: expected for _, expected, prompt in ITEMS}
    requests = []

    def fixture_call(**kwargs):
        requests.append(kwargs)
        assert kwargs["stream"] is True
        assert kwargs["provider"] == "nous" and kwargs["model"] == target.model
        kwargs["route_info"].update(provider=target.provider, model=target.model)
        prompt = kwargs["messages"][0]["content"]
        text = code_answers.get(prompt, "391" if "17 multiplied by 23" in prompt else "A")
        if "End with ####" in prompt:
            text = "#### 0"
        calls = []
        if prompt in tool_answers:
            expected = tool_answers[prompt]
            if expected is None:
                text = "56"
            else:
                text = ""
                calls = [
                    {"id": f"call-{i}", "type": "function", "function":
                        {"name": name, "arguments": json.dumps(arguments)}}
                    for i, (name, arguments) in enumerate(expected)
                ]
        return {"model": target.model, "choices": [{"index": 0,
            "message": {"content": text, "tool_calls": calls}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 6}}

    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", SimpleNamespace(call_llm=fixture_call))
    out = tmp_path / "result.json"
    # Deliberately omit --limit and --full: verify the actual standard defaults.
    argv = ["run", "--runtime-provider", "nous", "--runtime-model", target.model, "--",
            "--policy", "strict", "--thinking", "on", "--concurrency", "1",
            "--max-minutes", "1", "--artifact-id", "scope-fixture", "--out", str(out), "--no-resume"]
    if skip_code:
        argv.append("--skip-code-exec")
    # wraps calls the real subprocess implementation: candidate code IS executed.
    real_run = subprocess.run
    with patch("sixcat.code.subprocess.run", wraps=real_run) as executed:
        assert hermes.main(argv) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    expected_n = {cat: 0 if skip_code and cat == "code" else 20 for cat in CATEGORIES}
    assert result["n"] == result["expected_n"] == expected_n
    assert result["complete"] is True
    assert sum(result["n"].values()) == (100 if skip_code else 120)
    assert len(requests) == (101 if skip_code else 121)  # plus one unscored policy probe
    assert result["code_execution"] == ("disabled" if skip_code else "host-guarded")
    assert executed.call_count == (0 if skip_code else 20)
    if not skip_code:
        assert result["categories"]["code"] == 100
        assert len(result["items"]["code"]) == 20
        assert all(row["ok"] for row in result["items"]["code"])
        for call in executed.call_args_list:
            assert call.args[0][0] == sys.executable
            assert call.args[0][1:3] == ["-I", "-S"]
            assert 0 < call.kwargs["timeout"] <= 8.0
            assert call.kwargs["capture_output"] is True
            assert "SIXCAT_API_KEY" not in call.kwargs["env"]
    else:
        assert result["items"]["code"] == []
        assert result["categories"]["code"] is None
    assert out.with_suffix(".jsonl").is_file()
