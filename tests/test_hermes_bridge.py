"""Hermes bridge regression tests: no live credentials or model calls."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from sixcat import hermes as runner


@pytest.fixture
def target():
    return runner.HermesRuntimeTarget(profile="test", model="vendor/model:free", provider="nous",
        runtime={"api_key": "test-secret", "base_url": "https://example.invalid/v1", "api_mode": "chat_completions"})


class Stream:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.closed = False
    def __iter__(self):
        return self
    def __next__(self):
        item = next(self.chunks)
        if isinstance(item, Exception):
            raise item
        return item
    def close(self):
        self.closed = True


def chunk(delta=None, finish=None, **extra):
    return {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}], **extra}


def completion(text="SIXCAT_OK"):
    return {"model": "vendor/model:free", "choices": [{"index": 0,
        "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}


def fake_aux(monkeypatch, target, response=None):
    calls = []
    def call(**kwargs):
        calls.append(kwargs)
        kwargs["route_info"].update(provider=target.provider, model=target.model)
        return response if response is not None else completion()
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", SimpleNamespace(call_llm=call))
    monkeypatch.setattr(runner, "resolve_runtime_target", lambda **kwargs: target)
    return calls


def test_stream_assembles_tools_reasoning_and_trailing_usage(target):
    stream = Stream([
        chunk({"reasoning_content": "Check "}, id="receipt", model=target.model),
        chunk({"reasoning_content": "this.", "tool_calls": [{"index": 0, "id": "call_1", "type": "function",
             "function": {"name": "lookup", "arguments": '{"city":'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"LA"}'}}]}, "tool_calls"),
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
    ])
    calls = []
    def call(**kwargs):
        calls.append(kwargs)
        kwargs["route_info"].update(provider="nous", model=target.model)
        return stream
    result = runner.call_target({"model": target.model, "messages": [{"role": "user", "content": "x"}],
                                 "tool_choice": "auto", "parallel_tool_calls": False}, target, call_llm_fn=call)
    message = result["choices"][0]["message"]
    assert message["reasoning_content"] == "Check this."
    assert message["tool_calls"][0]["function"] == {"name": "lookup", "arguments": '{"city":"LA"}'}
    assert result["usage"]["completion_tokens"] == 5
    assert stream.closed and len(calls) == 1
    assert calls[0]["stream"] is True
    assert calls[0]["stream_options"] == {"include_usage": True}
    assert calls[0]["extra_body"]["tool_choice"] == "auto"
    assert calls[0]["extra_body"]["parallel_tool_calls"] is False


@pytest.mark.parametrize("chunks", [[], [chunk({"content": "partial"})],
    [chunk({"content": "partial"}), RuntimeError("connection reset")], [{"error": {"message": "upstream failed"}}]])
def test_broken_stream_is_not_a_scored_completion(chunks):
    stream = Stream(chunks)
    with pytest.raises(RuntimeError):
        runner.collect_response(stream)
    assert stream.closed


def test_completed_response_shim_and_length_are_preserved():
    response = completion("partial")
    response["choices"][0]["finish_reason"] = "length"
    assert runner.collect_response(response) == response


@pytest.mark.parametrize("response", [{"choices": []}, {"choices": [{"message": {}, "finish_reason": None}]}])
def test_incomplete_completed_object_is_rejected(response):
    with pytest.raises(RuntimeError):
        runner.collect_response(response)


def test_no_nonstream_retry_on_upstream_failure(target):
    calls = []
    def call(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("quota exhausted")
    with pytest.raises(RuntimeError, match="quota exhausted"):
        runner.call_target({"messages": [{"role": "user", "content": "x"}]}, target, call_llm_fn=call)
    assert len(calls) == 1 and calls[0]["stream"] is True


def test_older_hermes_fails_before_call(target):
    calls = []
    def old_call(messages):
        calls.append(messages)
    with pytest.raises(RuntimeError, match="update Hermes"):
        runner.call_target({"messages": [{"role": "user", "content": "x"}]}, target, call_llm_fn=old_call)
    assert not calls


def test_wrong_route_is_closed_without_reading(target):
    stream = Stream([RuntimeError("must not consume wrong model")])
    def call(**kwargs):
        kwargs["route_info"].update(provider="openrouter", model="paid-model")
        return stream
    with pytest.raises(RuntimeError, match="identity drift"):
        runner.call_target({"messages": [{"role": "user", "content": "x"}]}, target, call_llm_fn=call)
    assert stream.closed


@pytest.mark.parametrize("arg", ["--model=x", "--base=x", "--base-url=x", "--api-key=x", "--transport=stdio"])
def test_pinned_route_cannot_be_overridden_even_by_abbreviation(arg):
    with pytest.raises(ValueError, match="owns"):
        runner._forward_args(["--", arg])


def test_forward_args_leave_regular_flags_unchanged():
    assert runner._forward_args(["--", "--max-minutes", "30", "--policy", "strict"]) == ["--max-minutes", "30", "--policy", "strict"]


@pytest.mark.parametrize("name", [".", "..", "../other", "bad/profile"])
def test_profile_traversal_is_rejected(name):
    with pytest.raises(ValueError):
        runner.resolve_profile_home(name)


def test_current_profile_honors_sticky_selection(monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = tmp_path / ".hermes"
    selected = home / "profiles" / "bench"
    selected.mkdir(parents=True)
    (home / "active_profile").write_text("bench\n")
    assert runner.resolve_profile_home("current") == ("bench", selected)


def test_explicit_home_wins_over_sticky_selection(monkeypatch, tmp_path):
    home = tmp_path / "profiles" / "worker"
    home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    assert runner.resolve_profile_home("current") == ("worker", home)


def test_inspect_policy_and_json_do_not_claim_inference(monkeypatch, capsys, target):
    monkeypatch.setattr(runner, "resolve_runtime_target", lambda **kwargs: target)
    assert runner.main(["inspect", "--policy", "strict", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["resolved_policy"]["name"] == "strict"
    assert result["inference_verified"] is False
    assert result["billing_verified"] is False
    assert "test-secret" not in json.dumps(result)


def test_preflight_subcommand_accepts_documented_policy_flags(monkeypatch, capsys, target):
    calls = fake_aux(monkeypatch, target)
    assert runner.main(["preflight", "--", "--policy", "strict", "--thinking", "on", "--limit", "2", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["inference_verified"] is False
    assert not calls  # metadata/context estimate, not inference


def test_smoke_is_one_unscored_call_with_clean_json(monkeypatch, capsys, target):
    calls = fake_aux(monkeypatch, target)
    assert runner.main(["smoke", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["smoke_passed"] is True
    assert result["inference_verified"] is True
    assert result["benchmark_score"] is None
    assert result["billing_verified"] is False
    assert len(calls) == 1 and calls[0]["tools"] is None


def test_failed_smoke_does_not_start_benchmark(monkeypatch, capsys, target):
    calls = fake_aux(monkeypatch, target, completion("wrong"))
    assert runner.main(["smoke", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["smoke_passed"] is False
    assert len(calls) == 1


def test_import_failure_has_actionable_error_without_traceback(monkeypatch, capsys):
    def missing(**kwargs):
        raise ModuleNotFoundError("No module named hermes_cli")
    monkeypatch.setattr(runner, "resolve_runtime_target", missing)
    assert runner.main(["inspect"]) == 2
    result = capsys.readouterr()
    assert not result.out
    assert "Python 3.11+" in result.err and "Traceback" not in result.err
