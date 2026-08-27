from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sixcat.context_preflight import (
    CASE_EXCEEDS_CONTEXT,
    CTX_CONFLICT,
    CTX_INVALID_VALUE,
    CTX_STALE_CACHE,
    CTX_UNKNOWN,
    ETA_LOW_CONFIDENCE,
    MODEL_AMBIGUOUS,
    PROBE_TIMEOUT,
    USAGE_UNAVAILABLE,
    account_probe_usage,
    assemble_preflight,
    collect_llama_cpp_candidates,
    collect_openai_model_candidates,
    derive_input_budget,
    estimate_run_eta,
    evaluate_prompt_fit,
    format_preflight,
    match_models,
    parse_ctx_value,
    resolve_context,
)


class TestParseCtxValue(unittest.TestCase):
    def test_accepts_positive_int_and_numeric_string(self):
        self.assertEqual(parse_ctx_value(32768), 32768)
        self.assertEqual(parse_ctx_value("8192"), 8192)

    def test_rejects_bool_float_junk_zero_negative_and_absurd(self):
        for value in (True, False, 32768.5, 32768.0, "32768tokens", "32768.0", 0, -1, None, 99_000_000):
            with self.subTest(value=value):
                self.assertIsNone(parse_ctx_value(value))


class TestLlamaCppCandidates(unittest.TestCase):
    def test_top_level_n_ctx_only(self):
        candidates = collect_llama_cpp_candidates({"n_ctx": 4096})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["value"], 4096)
        self.assertEqual(candidates[0]["field_path"], "n_ctx")
        self.assertEqual(candidates[0]["layer"], "runtime_total_ctx")
        self.assertEqual(candidates[0]["source"], "llama_cpp_props")

    def test_nested_default_generation_n_ctx_only(self):
        candidates = collect_llama_cpp_candidates({"default_generation_settings": {"n_ctx": 2048}})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["value"], 2048)
        self.assertEqual(candidates[0]["field_path"], "default_generation_settings.n_ctx")

    def test_both_fields_are_retained_when_they_disagree(self):
        candidates = collect_llama_cpp_candidates(
            {"n_ctx": 32768, "default_generation_settings": {"n_ctx": 8192}}
        )
        values = sorted(item["value"] for item in candidates)
        self.assertEqual(values, [8192, 32768])


class TestOpenAIModelMatching(unittest.TestCase):
    def test_exact_model_match_reads_max_model_len(self):
        payload = {
            "data": [
                {"id": "embed", "max_model_len": 8192},
                {"id": "qwen3", "max_model_len": 32768, "context_length": 131072},
            ]
        }
        candidates, match = collect_openai_model_candidates(payload, "qwen3")
        self.assertEqual(match["status"], "exact")
        self.assertEqual(match["resolved_model"], "qwen3")
        values = {item["field_path"]: item["value"] for item in candidates}
        self.assertEqual(values["data[id=qwen3].max_model_len"], 32768)
        self.assertEqual(values["data[id=qwen3].context_length"], 131072)
        self.assertNotIn("data[id=embed].max_model_len", values)

    def test_several_models_and_no_exact_match_do_not_use_first_entry(self):
        payload = {
            "data": [
                {"id": "embed", "max_model_len": 8192},
                {"id": "rerank", "max_model_len": 4096},
            ]
        }
        candidates, match = collect_openai_model_candidates(payload, "qwen3")
        self.assertEqual(match["status"], "missing")
        self.assertEqual(candidates, [])

    def test_basename_alias_yields_one_match(self):
        payload = {"data": [{"id": "Qwen/Qwen3-8B", "max_model_len": 32768}]}
        candidates, match = collect_openai_model_candidates(payload, "Qwen3-8B")
        self.assertEqual(match["status"], "alias")
        self.assertEqual(match["rule"], "basename")
        self.assertEqual(match["resolved_model"], "Qwen/Qwen3-8B")
        self.assertEqual(candidates[0]["value"], 32768)

    def test_alias_normalization_with_several_matches_is_ambiguous(self):
        payload = {
            "data": [
                {"id": "org/Qwen3-8B", "max_model_len": 32768},
                {"id": "other/Qwen3-8B", "max_model_len": 16384},
            ]
        }
        candidates, match = collect_openai_model_candidates(payload, "Qwen3-8B")
        self.assertEqual(match["status"], "ambiguous")
        self.assertEqual(candidates, [])

    def test_casefold_alias_is_explicit(self):
        match = match_models("Qwen3", ["qwen3"])
        self.assertEqual(match["status"], "alias")
        self.assertEqual(match["rule"], "casefold")


class TestResolveContext(unittest.TestCase):
    def test_configured_override_wins_and_is_labeled_configured(self):
        resolved = resolve_context(
            [{"value": 32768, "source": "openai_models", "field_path": "max_model_len", "layer": "runtime_total_ctx", "model_id": "qwen3"}],
            requested_model="qwen3",
            configured_ctx=16384,
            model_match_status="exact",
            resolved_model="qwen3",
        )
        self.assertEqual(resolved["ctx_advertised"], 16384)
        self.assertEqual(resolved["ctx_source"], "configured")
        self.assertEqual(resolved["ctx_confidence"], "high")

    def test_runtime_disagreement_selects_smaller_value_and_conflicts(self):
        resolved = resolve_context(
            [
                {
                    "value": 32768,
                    "source": "llama_cpp_props",
                    "field_path": "n_ctx",
                    "layer": "runtime_total_ctx",
                    "model_id": None,
                },
                {
                    "value": 8192,
                    "source": "llama_cpp_props",
                    "field_path": "default_generation_settings.n_ctx",
                    "layer": "runtime_total_ctx",
                    "model_id": None,
                },
            ],
            requested_model="qwen3",
            model_match_status="exact",
            resolved_model="qwen3",
        )
        self.assertEqual(resolved["ctx_advertised"], 8192)
        codes = [item["code"] for item in resolved["warnings"]]
        self.assertIn(CTX_CONFLICT, codes)

    def test_ambiguous_model_match_returns_unknown(self):
        resolved = resolve_context(
            [
                {
                    "value": 32768,
                    "source": "openai_models",
                    "field_path": "data[id=a].max_model_len",
                    "layer": "runtime_total_ctx",
                    "model_id": "a",
                }
            ],
            requested_model="qwen3",
            model_match_status="ambiguous",
            resolved_model=None,
        )
        self.assertIsNone(resolved["ctx_advertised"])
        self.assertEqual(resolved["ctx_confidence"], "unknown")
        self.assertIn(MODEL_AMBIGUOUS, [item["code"] for item in resolved["warnings"]])

    def test_invalid_values_are_dropped_with_ctx_invalid_value(self):
        candidates = collect_llama_cpp_candidates({"n_ctx": True, "max_position_embeddings": -8})
        self.assertEqual(candidates, [])
        resolved = resolve_context(
            [],
            requested_model="qwen3",
            invalid_values=[{"field_path": "n_ctx", "raw": True}],
        )
        self.assertIsNone(resolved["ctx_advertised"])
        self.assertIn(CTX_INVALID_VALUE, [item["code"] for item in resolved["warnings"]])
        self.assertIn(CTX_UNKNOWN, [item["code"] for item in resolved["warnings"]])


class TestInputBudget(unittest.TestCase):
    def test_safety_margin_is_max_of_512_and_two_percent(self):
        derived = derive_input_budget(32768, output_reserve=1024)
        self.assertEqual(derived["safety_margin"], 656)
        self.assertEqual(derived["input_budget"], 31088)

    def test_prompt_can_fit_advertised_ctx_but_not_safe_budget(self):
        fit = evaluate_prompt_fit(prompt_tokens=31100, ctx_advertised=32768, output_reserve=1024)
        self.assertTrue(fit["fits_advertised"])
        self.assertFalse(fit["fits_input_budget"])
        self.assertEqual(fit["warning_code"], CASE_EXCEEDS_CONTEXT)


class TestProbeAccountingAndEta(unittest.TestCase):
    def test_prefers_api_usage_and_reports_reasoning_tokens(self):
        account = account_probe_usage(
            {
                "status": "ok",
                "finish": "stop",
                "prompt_tokens": 40,
                "completion_tokens": 256,
                "reasoning_tokens": 80,
                "wall_s": 4.0,
                "prefill_tps": 800.0,
                "decode_tps": 40.0,
            }
        )
        self.assertEqual(account["usage_source"], "api_usage")
        self.assertEqual(account["reasoning_tokens"], 80)
        self.assertTrue(account["tps_reliable"])

    def test_missing_usage_is_labeled_unavailable_not_heuristic_256(self):
        account = account_probe_usage({"status": "ok", "finish": "stop"})
        self.assertEqual(account["usage_source"], "unavailable")
        self.assertIn(USAGE_UNAVAILABLE, [item["code"] for item in account["warnings"]])

    def test_eta_is_a_range_with_confidence_not_a_single_number(self):
        account = account_probe_usage(
            {
                "status": "ok",
                "finish": "stop",
                "prompt_tokens": 40,
                "completion_tokens": 128,
                "reasoning_tokens": None,
                "wall_s": 3.0,
                "prefill_tps": 400.0,
                "decode_tps": 20.0,
            }
        )
        eta = estimate_run_eta(n_items=120, probe_account=account)
        self.assertIsInstance(eta["eta_low_s"], float)
        self.assertIsInstance(eta["eta_high_s"], float)
        self.assertGreater(eta["eta_high_s"], eta["eta_low_s"])
        self.assertIn(eta["confidence"], {"high", "medium", "low", "unknown"})
        self.assertIn(ETA_LOW_CONFIDENCE, [item["code"] for item in eta["warnings"]])
        self.assertNotEqual(eta["eta_low_s"], eta["eta_high_s"])

    def test_probe_timeout_does_not_invent_eta(self):
        account = account_probe_usage({"status": "failed", "reason": "probe request failed: timed out"})
        self.assertIn(PROBE_TIMEOUT, [item["code"] for item in account["warnings"]])
        eta = estimate_run_eta(n_items=120, probe_account=account)
        self.assertIsNone(eta["eta_low_s"])
        self.assertIsNone(eta["eta_high_s"])
        self.assertEqual(eta["confidence"], "unknown")


    def test_openai_payload_absent_is_not_model_not_found(self):
        from sixcat.context_preflight import MODEL_NOT_FOUND, assemble_preflight

        llama_only = assemble_preflight(
            requested_model="qwen3",
            server_props={"source": "llama_cpp_props", "llama_cpp_props": {"n_ctx": 4096}},
            probe={"status": "ok"},
            n_items=20,
            output_reserve=1024,
        )
        self.assertEqual(llama_only["ctx_advertised"], 4096)
        self.assertNotIn(MODEL_NOT_FOUND, [item["code"] for item in llama_only["warnings"]])

        unavailable = assemble_preflight(
            requested_model="qwen3",
            server_props={"source": "unavailable", "error": "down"},
            probe={"status": "ok"},
            n_items=20,
            output_reserve=1024,
        )
        self.assertIsNone(unavailable["ctx_advertised"])
        self.assertNotIn(MODEL_NOT_FOUND, [item["code"] for item in unavailable["warnings"]])

    def test_present_models_list_without_id_is_model_not_found(self):
        from sixcat.context_preflight import MODEL_NOT_FOUND, assemble_preflight

        result = assemble_preflight(
            requested_model="qwen3",
            server_props={
                "source": "openai_models",
                "openai_models": {"data": [{"id": "embed", "max_model_len": 8192}]},
            },
            probe={"status": "ok"},
            n_items=20,
            output_reserve=1024,
        )
        self.assertIn(MODEL_NOT_FOUND, [item["code"] for item in result["warnings"]])


class TestAssembleAndCache(unittest.TestCase):
    def test_assemble_keeps_candidates_and_does_not_score(self):
        preflight = assemble_preflight(
            requested_model="qwen3",
            server_props={
                "source": "openai_models",
                "openai_models": {"data": [{"id": "qwen3", "max_model_len": 32768}]},
            },
            probe={
                "status": "ok",
                "finish": "stop",
                "prompt_tokens": 40,
                "completion_tokens": 128,
                "wall_s": 2.0,
                "decode_tps": 32.0,
                "prefill_tps": 400.0,
            },
            n_items=120,
            output_reserve=1024,
        )
        self.assertEqual(preflight["requested_model"], "qwen3")
        self.assertEqual(preflight["resolved_model"], "qwen3")
        self.assertEqual(preflight["ctx_advertised"], 32768)
        self.assertEqual(preflight["phase"], "observe")
        self.assertNotIn("score", preflight)
        self.assertIn("ctx_candidates", preflight)
        text = format_preflight(preflight)
        self.assertIn("served context:", text)
        self.assertIn("safe input budget:", text)
        self.assertIn("ETA:", text)

    def test_fresh_contradictory_metadata_outranks_cache(self):
        cached = assemble_preflight(
            requested_model="qwen3",
            server_props={
                "source": "openai_models",
                "openai_models": {"data": [{"id": "qwen3", "max_model_len": 8192}]},
            },
            probe={"status": "ok", "finish": "stop"},
            n_items=20,
            output_reserve=1024,
            cache_key="http://127.0.0.1:8000/v1|qwen3|chat",
            store_cache=True,
        )
        self.assertEqual(cached["ctx_advertised"], 8192)
        fresh = assemble_preflight(
            requested_model="qwen3",
            server_props={
                "source": "openai_models",
                "openai_models": {"data": [{"id": "qwen3", "max_model_len": 32768}]},
            },
            probe={"status": "ok", "finish": "stop"},
            n_items=20,
            output_reserve=1024,
            cache_key="http://127.0.0.1:8000/v1|qwen3|chat",
            cached=cached,
        )
        self.assertEqual(fresh["ctx_advertised"], 32768)
        self.assertIn(CTX_STALE_CACHE, [item["code"] for item in fresh["warnings"]])

    def test_cache_expires_and_never_replaces_fresh_unknown_with_stale_value(self):
        assemble_preflight(
            requested_model="qwen3",
            server_props={
                "source": "openai_models",
                "openai_models": {"data": [{"id": "qwen3", "max_model_len": 8192}]},
            },
            probe={"status": "ok"},
            n_items=20,
            output_reserve=1024,
            cache_key="k",
            store_cache=True,
            now=100.0,
        )
        with patch("sixcat.context_preflight.CACHE_TTL_S", 1.0):
            expired = assemble_preflight(
                requested_model="qwen3",
                server_props={"source": "unavailable", "error": "down"},
                probe={"status": "ok"},
                n_items=20,
                output_reserve=1024,
                cache_key="k",
                now=200.0,
                use_cache=True,
            )
        self.assertIsNone(expired["ctx_advertised"])
        self.assertIn(CTX_UNKNOWN, [item["code"] for item in expired["warnings"]])


class TestFetchServerPropsBothSources(unittest.TestCase):
    def test_fetch_server_props_records_props_and_models_independently(self):
        from sixcat.client import fetch_server_props

        payloads = {
            "http://host/props": {"n_ctx": 4096},
            "http://host/v1/models": {"data": [{"id": "qwen3", "max_model_len": 32768}]},
        }

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                import json

                return json.dumps(self._payload).encode()

        def fake_urlopen(req, timeout=10.0):
            url = getattr(req, "full_url", None) or req
            return FakeResp(payloads[url])

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = fetch_server_props("http://host/v1", timeout=1.0)

        self.assertEqual(result["source"], "llama_cpp_props")
        self.assertEqual(result["llama_cpp_props"]["n_ctx"], 4096)
        self.assertEqual(result["openai_models"]["data"][0]["id"], "qwen3")


class TestRunBatteryObserveOnly(unittest.TestCase):
    def test_run_battery_records_preflight_without_changing_scores(self):
        from sixcat.policy import strict_policy
        from sixcat.run import render_table, run_battery

        policy = strict_policy()

        class FakeClient:
            def __init__(self):
                self.policy = policy
                self.model = "qwen3"
                self.base_url = "http://fixture/v1"
                self.api_key = "none"

            def complete(self, prompt, **kwargs):
                return {
                    "text": "391",
                    "reasoning_content": "",
                    "finish": "stop",
                    "usage": {"prompt_tokens": 12, "completion_tokens": 80},
                    "wall_s": 2.0,
                    "prefill_tps": 200.0,
                    "decode_tps": 40.0,
                }

        rows = [{"ok": True, "finish": "stop", "ctok": 2, "parse_confidence": "high"}]
        server_props = {
            "source": "openai_models",
            "props": {"data": [{"id": "qwen3", "max_model_len": 32768}]},
            "openai_models": {"data": [{"id": "qwen3", "max_model_len": 32768}]},
        }
        with (
            patch("sixcat.run.fetch_server_props", return_value=server_props),
            patch("sixcat.run.run_knowledge", return_value=rows),
            patch("sixcat.run.run_math", return_value=rows),
            patch("sixcat.run.run_truth", return_value=rows),
            patch("sixcat.run.run_instruct", return_value=rows),
            patch("sixcat.run.run_code", return_value=rows),
            patch("sixcat.run.run_tools", return_value=rows),
        ):
            result = run_battery(FakeClient(), limit=1, skip_code_exec=False)

        self.assertEqual(result["overall"], {"policy": "strict", "score": 100.0})
        self.assertEqual(result["preflight"]["phase"], "observe")
        self.assertEqual(result["preflight"]["ctx_advertised"], 32768)
        table = render_table(result)
        self.assertIn("Preflight", table)
        self.assertIn("served context:", table)
        self.assertNotIn("score +", table.lower())


class TestPreflightCli(unittest.TestCase):
    def test_preflight_subcommand_prints_observe_json_without_scoring(self):
        import io
        from contextlib import redirect_stdout

        from sixcat.__main__ import main

        payload = {
            "source": "openai_models",
            "openai_models": {"data": [{"id": "qwen3", "max_model_len": 32768}]},
            "props": {"data": [{"id": "qwen3", "max_model_len": 32768}]},
        }
        buf = io.StringIO()
        with patch("sixcat.client.fetch_server_props", return_value=payload), redirect_stdout(buf):
            rc = main(["preflight", "--model", "qwen3", "--json"])
        self.assertEqual(rc, 0)
        document = json.loads(buf.getvalue())
        self.assertEqual(document["phase"], "observe")
        self.assertEqual(document["ctx_advertised"], 32768)
        self.assertNotIn("score", document)
        self.assertNotIn("categories", document)


if __name__ == "__main__":
    unittest.main()
