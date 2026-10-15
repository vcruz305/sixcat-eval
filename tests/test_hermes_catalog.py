"""Offline checks for the one-line model resolver; fixture IDs are not live offers."""
from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sixcat import hermes, hermes_catalog as catalog


FREE_ID = "fixture/nemotron-3-ultra:free"
PAID_ID = "fixture/nemotron-3-ultra"


def model(identifier=FREE_ID, **fields):
    return {"id": identifier, "name": "Fixture Nemotron 3 Ultra", **fields}


def test_user_sentence_model_resolves_without_manufacturing_id():
    receipt = catalog.match_catalog("Nemotron ultra free", [model(PAID_ID), model()])
    assert receipt["status"] == "resolved"
    assert receipt["model"] == FREE_ID
    assert receipt["free_required"] is True
    assert receipt["inference_verified"] is False
    assert receipt["billing_verified"] is False


@pytest.mark.parametrize("query", ["NEMOTRON ULTRA FREE", "Nemotron-ultra (free)", FREE_ID])
def test_case_punctuation_and_exact_id(query):
    assert catalog.match_catalog(query, [model()])["model"] == FREE_ID


def test_display_name_can_supply_missing_words():
    row = {"id": "fixture/ultra-special", "name": "Nemotron Ultra (free)"}
    assert catalog.match_catalog("Nemotron ultra free", [row])["model"] == row["id"]


def test_exact_id_does_not_become_a_different_free_model():
    receipt = catalog.match_catalog(PAID_ID, [model(PAID_ID, pricing={"prompt": "1", "completion": "2"}), model()], free_only=True)
    assert receipt["status"] == "not_found" and receipt["model"] is None


def test_free_only_flag_checks_prices_even_without_free_suffix():
    row = model(PAID_ID, pricing={"prompt": "0", "completion": "0.000"})
    receipt = catalog.match_catalog("Nemotron ultra", [row], free_only=True)
    assert receipt["model"] == PAID_ID
    assert receipt["candidates"][0]["free_evidence"] == "catalog_zero_prompt_and_completion_price"


@pytest.mark.parametrize("pricing", [
    {"prompt": "0.5", "completion": "2"}, {"prompt": "0"},
    {"prompt": "NaN", "completion": "0"}, {"prompt": "Infinity", "completion": "0"},
    {"prompt": None, "completion": "0"}, {"prompt": False, "completion": 0},
    {"prompt": "-1", "completion": "0"}, {"prompt": "0", "completion": "bad"},
])
def test_nonzero_or_malformed_pricing_never_overridden_by_free_label(pricing):
    receipt = catalog.match_catalog("Nemotron ultra free", [model(pricing=pricing)])
    assert receipt["status"] == "not_found"


def test_subscription_evidence_is_not_free_billing_attestation():
    receipt = catalog.match_catalog("Nemotron ultra free", [model(PAID_ID, billing_mode="subscription")])
    assert receipt["model"] == PAID_ID
    assert "subscription" in receipt["candidates"][0]["free_evidence"]
    assert receipt["billing_verified"] is False


def test_unknown_price_without_free_label_is_not_selected():
    assert catalog.match_catalog("Nemotron ultra free", [model(PAID_ID)])["status"] == "not_found"


def test_two_free_variants_require_one_choice_not_arbitrary_ranking():
    rows = [model(), model("fixture/nemotron-4-ultra:free")]
    result = catalog.match_catalog("Nemotron ultra free", rows)
    assert result["status"] == "ambiguous" and result["model"] is None
    assert len(result["candidates"]) == 2


def test_paid_and_free_ambiguous_without_free_requirement():
    assert catalog.match_catalog("Nemotron ultra", [model(PAID_ID), model()])["status"] == "ambiguous"


def test_no_substring_matching_for_ultra_vs_super():
    assert catalog.match_catalog("Nemotron ultra free", [{"id": "fixture/nemotron-super:free"}])["status"] == "not_found"


def test_duplicates_and_malformed_rows():
    receipt = catalog.match_catalog("Nemotron ultra free", [None, "bad", {}, model(), model()])
    assert receipt["model"] == FREE_ID and len(receipt["candidates"]) == 1


@pytest.mark.parametrize("query", ["", "   ", "free", "()"])
def test_query_requires_a_model(query):
    with pytest.raises(ValueError):
        catalog.match_catalog(query, [])


def fake_runtime(monkeypatch, tmp_path, *, status=200, payload=None, runtime=None):
    calls = []
    home = tmp_path / "profile"
    home.mkdir()
    monkeypatch.setattr(hermes, "resolve_profile_home", lambda profile: ("test", home))
    monkeypatch.setitem(sys.modules, "hermes_cli.env_loader", SimpleNamespace(load_hermes_dotenv=lambda **kw: None))
    monkeypatch.setitem(sys.modules, "hermes_cli.anon_challenge", SimpleNamespace(background_caller=nullcontext))
    def resolve(**kwargs):
        calls.append(("runtime", kwargs))
        return runtime or {"provider": "nous", "base_url": "https://catalog.example.invalid/v1", "api_key": "fixture-secret"}
    monkeypatch.setitem(sys.modules, "hermes_cli.runtime_provider", SimpleNamespace(resolve_runtime_provider=resolve))
    data = payload if payload is not None else {"data": [model()]}
    response = SimpleNamespace(status_code=status, content=json.dumps(data).encode(), json=lambda: data)
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False and kwargs["timeout"] == 15.0
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, **kwargs):
            calls.append(("get", url))
            assert kwargs["headers"]["Authorization"] == "Bearer fixture-secret"
            return response
    import httpx
    monkeypatch.setattr(httpx, "Client", Client)
    return calls


def test_live_catalog_uses_only_resolved_endpoint_no_generation(monkeypatch, tmp_path):
    calls = fake_runtime(monkeypatch, tmp_path)
    result = catalog.resolve_nous_query("current", "Nemotron ultra free")
    assert calls == [("runtime", {"requested": "nous"}), ("get", "https://catalog.example.invalid/v1/models")]
    assert result["model"] == FREE_ID and result["provider"] == "nous"
    assert "fixture-secret" not in json.dumps(result)


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500])
def test_catalog_errors_no_static_fallback(monkeypatch, tmp_path, status):
    calls = fake_runtime(monkeypatch, tmp_path, status=status)
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        catalog.resolve_nous_query("current", "Nemotron ultra free")
    assert len(calls) == 2


@pytest.mark.parametrize("runtime", [
    {"provider": "openrouter"},
    {"provider": "nous", "base_url": "http://catalog.invalid/v1", "api_key": "fixture-secret"},
    {"provider": "nous", "base_url": "https://user:pass@catalog.invalid/v1", "api_key": "fixture-secret"},
    {"provider": "nous", "base_url": "https://catalog.invalid/v1?token=x", "api_key": "fixture-secret"},
    {"provider": "nous", "base_url": "https://catalog.invalid/v1", "api_key": ""},
])
def test_unsafe_or_missing_runtime_stops_before_get(monkeypatch, tmp_path, runtime):
    calls = fake_runtime(monkeypatch, tmp_path, runtime=runtime)
    with pytest.raises(RuntimeError):
        catalog.resolve_nous_query("current", "Nemotron ultra free")
    assert len(calls) == 1


def test_callable_key_and_invalid_catalog_shape(monkeypatch, tmp_path):
    fake_runtime(monkeypatch, tmp_path, payload={"data": "not-a-list"}, runtime={
        "provider": "nous", "base_url": "https://catalog.example.invalid/v1", "api_key": lambda: "fixture-secret"})
    with pytest.raises(RuntimeError, match="no model list"):
        catalog.resolve_nous_query("current", "Nemotron ultra free")


@pytest.mark.parametrize("status,code", [("resolved", 0), ("ambiguous", 2), ("not_found", 2)])
def test_resolve_cli_does_not_instantiate_inference_target(monkeypatch, capsys, status, code):
    def no_target(**kwargs):
        pytest.fail("catalog discovery must not construct a generation target")
    monkeypatch.setattr(hermes, "resolve_runtime_target", no_target)
    monkeypatch.setattr(catalog, "resolve_nous_query", lambda profile, query, free_only: {"status": status, "query": query})
    assert hermes.main(["resolve", "--model-query", "Nemotron ultra free", "--json"]) == code
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_readme_skill_and_guide_have_same_one_line_contract():
    root = Path(__file__).resolve().parents[1]
    sentence = "Run sixcat eval against the Hermes provider nous portal and the model Nemotron ultra free."
    for path in (root / "README.md", root / "docs/hermes-nous.md", root / ".hermes/skills/sixcat-eval/SKILL.md"):
        assert sentence in path.read_text()
    skill = (root / ".hermes/skills/sixcat-eval/SKILL.md").read_text()
    assert skill.index("## One-line requests") < skill.index("## Procedure (optional interactive wizard)")
    for phrase in ("takes precedence", "Do not ask for policy", "free is a constraint", "Code N/A", "unless overridden"):
        assert phrase in skill
    assert "the **very next interaction**" not in skill
    assert "When the user already supplied the target, policy, scope, thinking setting" not in skill
