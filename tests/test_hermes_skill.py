from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".hermes" / "skills" / "sixcat-eval"


def _load_script(name: str):
    path = SKILL_DIR / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"sixcat_skill_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_project_skill_has_safe_frontmatter_and_conversational_workflow():
    path = SKILL_DIR / "SKILL.md"
    content = path.read_text(encoding="utf-8")

    assert content.startswith("---\n")
    frontmatter, body = content[4:].split("\n---\n", 1)
    fields = {
        line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip().strip('"')
        for line in frontmatter.splitlines()
        if ":" in line and not line.startswith(" ")
    }
    assert fields["name"] == "sixcat-eval"
    assert fields["description"].endswith(".")
    assert len(fields["description"]) <= 60
    assert "requires_toolsets: [terminal]" in frontmatter
    assert "Victor Cruz (vcruz305), Hermes Agent" in frontmatter
    for required in (
        "hermes skills trust",
        "detect",
        "model",
        "temperature",
        "Standard",
        "Quick",
        "Full",
        "Custom",
        "process",
        "live status",
        "policy fingerprint",
        "identity guard",
        "parser identity: `v4`",
        "broadcast one credential",
        "host-guarded",
        "skip-code-exec",
        "not a security sandbox",
        "Thinking on (recommended when supported)",
        "Do not start, stop, or replace",
    ):
        assert required.casefold() in body.casefold()
    assert "C:/Users/" not in content
    assert "/home/" not in content


def test_skill_asks_for_target_before_endpoint_detection_and_recommends_current_model():
    content = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    body = content.split("\n---\n", 1)[1]

    target_question = "model I am currently running"
    assert target_question.casefold() in body.casefold()
    assert body.casefold().index(target_question.casefold()) < body.casefold().index("detect the endpoint")
    assert "current Hermes session model (recommended)".casefold() in body.casefold()
    assert "another Hermes profile".casefold() in body.casefold()
    assert "alternate OpenAI-compatible endpoint".casefold() in body.casefold()
    assert "agent facade".casefold() in body.casefold()
    assert "raw model".casefold() in body.casefold()


def test_skill_questions_have_plain_english_explainers_distinct_emojis_and_custom_sampling():
    content = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    body = content.split("\n---\n", 1)[1]

    for emoji in ("🧠", "👤", "🔌", "🎛️", "🧊", "🏷️", "🔬", "⚖️", "⚡", "🧭", "🛠️", "🧪", "🛡️", "🚫"):
        assert emoji in body
    for explainer in (
        "20 scored items per category",
        "about 120 scored rows total",
        "temperature controls randomness",
        "top-p, top-k, and min-p filter",
        "thinking controls whether",
        "seed helps repeat",
        "some endpoints ignore it",
        "vendor-recommended temperature/settings",
        "unknown or stealth model",
        "custom sampling",
        "not a security sandbox",
    ):
        assert explainer.casefold() in body.casefold()
    assert "Do not offer Both when no reviewed vendor mapping exists".casefold() in body.casefold()
    assert "Items per dataset".casefold() not in body.casefold()


def test_hermes_runner_proxy_forwards_sampling_tools_and_exact_runtime_identity():
    runner = _load_script("hermes_runner.py")
    target = runner.HermesRuntimeTarget(
        profile="xavier",
        model="gpt-5.6-sol",
        provider="openai-codex",
        runtime={
            "api_key": "SUPER-SECRET",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_mode": "codex_responses",
        },
    )
    calls = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        kwargs["route_info"].update({"provider": "openai-codex", "model": "gpt-5.6-sol"})
        message = SimpleNamespace(
            content="B",
            reasoning_content="checked",
            tool_calls=[
                SimpleNamespace(
                    id="call_1",
                    type="function",
                    function=SimpleNamespace(name="read_file", arguments='{"path":"README.md"}'),
                )
            ],
        )
        return SimpleNamespace(
            id="chatcmpl-fixture",
            model="gpt-5.6-sol",
            choices=[SimpleNamespace(index=0, message=message, finish_reason="tool_calls")],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        )

    from sixcat.client import ChatClient
    from sixcat.policy import Policy

    policy = Policy(
        name="vendor",
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        min_p=0.0,
        thinking=True,
        budgets={"knowledge": 768},
        extra={"seed": 1, "presence_penalty": 0.0},
        source="fixture",
    )
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]

    with runner.proxy_server(target, call_llm_fn=fake_call_llm) as proxy:
        out = ChatClient(
            proxy.base_url,
            target.model,
            policy,
            api_key=proxy.api_key,
        ).complete("Choose B", max_tokens=321, tools=tools)

    assert out["text"] == "B"
    assert out["reasoning_content"] == "checked"
    assert out["finish"] == "tool_calls"
    assert out["usage"] == {"prompt_tokens": 11, "completion_tokens": 7}
    assert out["tool_calls"][0]["function"]["name"] == "read_file"
    assert len(calls) == 1
    call = calls[0]
    assert call["provider"] == "openai-codex"
    assert call["model"] == "gpt-5.6-sol"
    assert call["temperature"] == 0.6
    assert call["max_tokens"] == 321
    assert call["tools"] == tools
    assert call["reasoning_config"] == {"enabled": True}
    assert call["extra_body"] == {
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "seed": 1,
        "presence_penalty": 0.0,
        "chat_template_kwargs": {"enable_thinking": True},
    }


def test_hermes_runner_public_receipt_never_exposes_runtime_credentials():
    runner = _load_script("hermes_runner.py")
    secret = "SUPER-SECRET-RUNTIME-TOKEN"
    target = runner.HermesRuntimeTarget(
        profile="xavier",
        model="gpt-5.6-sol",
        provider="openai-codex",
        runtime={
            "api_key": secret,
            "credential_pool": object(),
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_mode": "codex_responses",
        },
    )

    receipt = runner.public_target_receipt(target)

    assert receipt == {
        "status": "ready",
        "target_kind": "hermes_runtime_model",
        "profile": "xavier",
        "model": "gpt-5.6-sol",
        "provider": "openai-codex",
        "api_mode": "codex_responses",
        "auth": "resolved",
    }
    assert secret not in json.dumps(receipt)


def test_hermes_runner_finds_checkout_from_env_when_installed_outside_repo(monkeypatch, tmp_path: Path):
    runner = _load_script("hermes_runner.py")
    installed_script = tmp_path / "profiles" / "xavier" / "skills" / "sixcat-eval" / "scripts" / "runner.py"
    monkeypatch.setenv("SIXCAT_PROJECT_ROOT", str(ROOT))
    monkeypatch.chdir(tmp_path)

    assert runner.find_project_root(script_path=installed_script) == ROOT


def test_hermes_runner_rejects_silent_provider_or_model_fallback():
    runner = _load_script("hermes_runner.py")

    with pytest.raises(RuntimeError, match="identity drift"):
        runner.require_exact_route(
            {"provider": "openrouter", "model": "other-model"},
            expected_provider="openai-codex",
            expected_model="gpt-5.6-sol",
        )


def test_preflight_normalizes_endpoint_and_previews_reviewed_policy():
    preflight = _load_script("preflight.py")

    assert preflight.normalize_base_url("http://127.0.0.1:8083") == "http://127.0.0.1:8083/v1"
    assert preflight.normalize_base_url("http://127.0.0.1:8083/v1/") == "http://127.0.0.1:8083/v1"

    preview = preflight.policy_preview("ornith-aeon-35b")
    assert preview["recommended_policy"] == "vendor"
    assert preview["resolved_policy"]["name"] == "vendor"
    assert preview["resolved_policy"]["temperature"] == 0.6
    assert preview["resolved_policy"]["thinking"] is True
    assert preview["resolved_policy"]["extra"]["seed"] == 1
    assert preview["policy_fingerprint"]
    assert preview["policy_source"].startswith("vendor:")


def test_preflight_selects_one_endpoint_and_refuses_ambiguity():
    preflight = _load_script("preflight.py")
    one = [{"base_url": "http://127.0.0.1:8083/v1", "models": ["ornith-aeon-35b"]}]
    ready = preflight.select_target(one, requested_model=None)
    assert ready == {
        "status": "ready",
        "base_url": "http://127.0.0.1:8083/v1",
        "model": "ornith-aeon-35b",
        "models": ["ornith-aeon-35b"],
    }

    two_endpoints = one + [{"base_url": "http://127.0.0.1:8000/v1", "models": ["other"]}]
    assert preflight.select_target(two_endpoints, requested_model=None)["status"] == "ambiguous_endpoints"
    several_models = [{"base_url": "http://127.0.0.1:8083/v1", "models": ["a", "b"]}]
    assert preflight.select_target(several_models, requested_model=None)["status"] == "ambiguous_models"
    selected = preflight.select_target(several_models, requested_model="b")
    assert selected["status"] == "ready"
    assert selected["model"] == "b"


def test_preflight_never_broadcasts_one_credential_during_discovery(monkeypatch):
    preflight = _load_script("preflight.py")
    calls = []

    def fake_probe(base_url, *, api_key="none", timeout=5.0):
        calls.append((base_url, api_key, timeout))
        return {"base_url": base_url, "reachable": True, "models": ["model"]}

    monkeypatch.setattr(preflight, "probe_endpoint", fake_probe)
    result = preflight.build_preflight(
        list(preflight.DEFAULT_CANDIDATES),
        api_key="real-secret",
    )

    assert result["status"] == "credential_requires_single_endpoint"
    assert calls == []
    assert preflight._headers("none") == {}
    assert preflight._headers("") == {}
    with pytest.raises(ValueError, match="single endpoint"):
        preflight.discover_endpoints(list(preflight.DEFAULT_CANDIDATES), api_key="real-secret")


def test_preflight_sends_credential_only_to_one_explicit_endpoint(monkeypatch):
    preflight = _load_script("preflight.py")
    calls = []

    def fake_probe(base_url, *, api_key="none", timeout=5.0):
        calls.append((base_url, api_key, timeout))
        return {"base_url": preflight.normalize_base_url(base_url), "reachable": True, "models": ["model"]}

    monkeypatch.setattr(preflight, "probe_endpoint", fake_probe)
    result = preflight.build_preflight(
        ["http://127.0.0.1:8083/v1"],
        api_key="real-secret",
    )

    assert result["status"] == "ready"
    assert calls == [("http://127.0.0.1:8083/v1", "real-secret", 5.0)]
    assert preflight._headers("real-secret") == {"Authorization": "Bearer real-secret"}


def test_status_summarizes_journal_and_ignores_incomplete_tail(tmp_path: Path):
    status = _load_script("status.py")
    journal = tmp_path / "run.jsonl"
    rows = [
        {"cat": "knowledge", "key": "mmlu:0", "ok": True, "finish": "stop", "loop": False, "ts": 10.0},
        {"cat": "knowledge", "key": "mmlu:1", "ok": False, "finish": "length", "loop": True, "parse_confidence": "low", "ts": 12.5},
        {"cat": "math", "key": "gsm:0", "ok": True, "finish": "stop", "loop": False, "ts": 15.0},
    ]
    journal.write_text("\n".join(json.dumps(row) for row in rows) + "\n{incomplete", encoding="utf-8")

    summary = status.summarize_journal(journal)
    assert summary["rows"] == 3
    assert summary["passed"] == 2
    assert summary["failed"] == 1
    assert summary["truncated"] == 1
    assert summary["loop_failures"] == 1
    assert summary["low_confidence"] == 1
    assert summary["latest"] == "math/gsm:0"
    assert summary["elapsed_s"] == 5.0
    assert summary["categories"]["knowledge"] == {"rows": 2, "passed": 1, "failed": 1}
    assert summary["invalid_lines"] == []


def test_status_surfaces_corrupt_interior_journal_rows(tmp_path: Path):
    status = _load_script("status.py")
    journal = tmp_path / "run.jsonl"
    journal.write_text(
        json.dumps({"cat": "knowledge", "key": "mmlu:0", "ok": True})
        + "\n{corrupt}\n"
        + json.dumps({"cat": "math", "key": "gsm:0", "ok": False})
        + "\n",
        encoding="utf-8",
    )

    summary = status.summarize_journal(journal)
    assert summary["rows"] == 2
    assert summary["invalid_lines"] == [2]


def test_status_skips_and_reports_run_identity_header(tmp_path: Path):
    status = _load_script("status.py")
    journal = tmp_path / "run.jsonl"
    identity = {
        "model": "model-a",
        "policy": "vendor",
        "policy_fingerprint": "abc123def456",
        "limit": 20,
    }
    journal.write_text(
        json.dumps({"_sixcat_run": identity})
        + "\n"
        + json.dumps({"cat": "truth", "key": "tqa:0", "ok": True})
        + "\n",
        encoding="utf-8",
    )

    summary = status.summarize_journal(journal)
    assert summary["rows"] == 1
    assert summary["passed"] == 1
    assert summary["failed"] == 0
    assert summary["run_identity"] == identity
