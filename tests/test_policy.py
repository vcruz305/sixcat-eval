from __future__ import annotations

import dataclasses
import unittest


class TestPolicyValue(unittest.TestCase):
    def test_policy_is_frozen_and_fingerprint_is_canonical(self):
        from sixcat.policy import Policy

        left = Policy(
            name="vendor",
            temperature=0.6,
            top_p=0.95,
            top_k=20,
            min_p=None,
            thinking=True,
            budgets={"math": 2048, "knowledge": 768},
            extra={"seed": 1, "presence_penalty": 0.0},
            source="reviewed-card",
        )
        right = Policy(
            name="vendor",
            temperature=0.6,
            top_p=0.95,
            top_k=20,
            min_p=None,
            thinking=True,
            budgets={"knowledge": 768, "math": 2048},
            extra={"presence_penalty": 0.0, "seed": 1},
            source="reviewed-card",
        )

        self.assertEqual(left.fingerprint, right.fingerprint)
        self.assertRegex(left.fingerprint, r"^[0-9a-f]{12}$")
        self.assertEqual(left.to_dict()["source"], "reviewed-card")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            left.name = "strict"  # type: ignore[misc]

    def test_policy_defensively_copies_source_mappings_and_keeps_fingerprint_stable(self):
        from sixcat.policy import Policy

        budgets = {"math": 2048}
        extra = {"metadata": {"reviewed": True}}
        policy = Policy("vendor", 0.6, 0.95, 20, None, True, budgets, extra, "test")
        fingerprint = policy.fingerprint

        budgets["math"] = 1
        extra["metadata"]["reviewed"] = False
        extra["max_tokens"] = 1

        self.assertEqual(policy.budgets["math"], 2048)
        self.assertEqual(policy.extra["metadata"]["reviewed"], True)
        self.assertNotIn("max_tokens", policy.extra)
        self.assertEqual(policy.fingerprint, fingerprint)

    def test_policy_mapping_fields_and_nested_values_are_immutable(self):
        from sixcat.policy import Policy

        policy = Policy(
            "vendor",
            0.6,
            0.95,
            20,
            None,
            True,
            {"math": 2048},
            {"metadata": {"reviewed": True}},
            "test",
        )
        fingerprint = policy.fingerprint

        with self.assertRaises(TypeError):
            policy.budgets["math"] = 1  # type: ignore[index]
        with self.assertRaises(TypeError):
            policy.extra["max_tokens"] = 1  # type: ignore[index]
        with self.assertRaises(TypeError):
            policy.extra["metadata"]["reviewed"] = False  # type: ignore[index]

        self.assertEqual(policy.fingerprint, fingerprint)
        self.assertNotIn("max_tokens", policy.extra)

    def test_policy_to_dict_returns_fresh_json_serializable_plain_containers(self):
        import json

        from sixcat.policy import Policy

        policy = Policy(
            "vendor",
            0.6,
            0.95,
            20,
            None,
            True,
            {"math": 2048},
            {"metadata": {"labels": ["reviewed"]}},
            "test",
        )

        first = policy.to_dict()
        self.assertIs(type(first["budgets"]), dict)
        self.assertIs(type(first["extra"]), dict)
        self.assertIs(type(first["extra"]["metadata"]), dict)
        self.assertIs(type(first["extra"]["metadata"]["labels"]), list)
        json.dumps(first)

        first["budgets"]["math"] = 1
        first["extra"]["metadata"]["labels"].append("changed")
        second = policy.to_dict()
        self.assertEqual(second["budgets"]["math"], 2048)
        self.assertEqual(second["extra"]["metadata"]["labels"], ["reviewed"])

    def test_policy_rejects_invalid_sampling_and_budget_settings(self):
        from sixcat.policy import Policy

        valid = {
            "name": "vendor",
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 20,
            "min_p": None,
            "thinking": True,
            "budgets": {"math": 2048},
            "extra": {},
            "source": "test",
        }
        invalid = (
            ("temperature", -0.1),
            ("top_p", 1.1),
            ("top_k", -1),
            ("min_p", 1.1),
            ("thinking", "yes"),
            ("budgets", {"math": 0}),
        )
        for field_name, value in invalid:
            kwargs = {**valid, field_name: value}
            with self.subTest(field=field_name), self.assertRaisesRegex(ValueError, field_name):
                Policy(**kwargs)


class TestPolicyResolution(unittest.TestCase):
    def _assert_invalid_policy_entry(self, field_name, value, message):
        import json
        import tempfile
        from pathlib import Path

        from sixcat.policy import resolve_policy

        entry = {
            "family": "test-family",
            "reviewed_date": "2026-08-20",
            "patterns": ["test-model"],
            "verified": True,
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 20,
            "min_p": None,
            "thinking": True,
            "extra": {},
            "source_url": "https://example.com/model-card",
        }
        entry[field_name] = value
        document = {"schema_version": 1, "policies": [entry]}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policies.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, message):
                resolve_policy("vendor", "test-model", policy_file=path, seed=1)

    def test_policy_file_requires_verified_to_be_exact_boolean_true(self):
        for value in ("false", 1):
            with self.subTest(value=value):
                self._assert_invalid_policy_entry("verified", value, "verified")

    def test_policy_file_rejects_blank_family(self):
        self._assert_invalid_policy_entry("family", "   ", "family")

    def test_policy_file_requires_non_empty_list_of_non_empty_string_patterns(self):
        for value in ("ornith", [], ["   "]):
            with self.subTest(value=value):
                self._assert_invalid_policy_entry("patterns", value, "patterns")

    def test_policy_file_rejects_invalid_exclude_patterns(self):
        for value in ("coder", ["   "], [1]):
            with self.subTest(value=value):
                self._assert_invalid_policy_entry("exclude_patterns", value, "exclude_patterns")

    def test_policy_file_rejects_invalid_required_patterns(self):
        for value in ("instruct", [], ["   "], [1]):
            with self.subTest(value=value):
                self._assert_invalid_policy_entry("required_patterns", value, "required_patterns")

    def test_required_patterns_prevent_unqualified_base_match(self):
        import json
        import tempfile
        from pathlib import Path

        from sixcat.policy import resolve_policy

        document = {
            "schema_version": 1,
            "policies": [
                {
                    "family": "test-family",
                    "reviewed_date": "2026-08-21",
                    "patterns": ["test-model"],
                    "required_patterns": ["instruct", "chat"],
                    "verified": True,
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "min_p": None,
                    "thinking": False,
                    "extra": {},
                    "source_url": "https://example.com/model-card",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policies.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            included = resolve_policy("vendor", "test-model-instruct-8b", policy_file=path)
            with self.assertWarnsRegex(RuntimeWarning, "falling back to strict"):
                excluded = resolve_policy("vendor", "test-model-8b", policy_file=path)

        self.assertEqual(included.name, "vendor")
        self.assertEqual(excluded.name, "strict")

    def test_exclude_patterns_prevent_a_broad_family_match(self):
        import json
        import tempfile
        from pathlib import Path

        from sixcat.policy import resolve_policy

        document = {
            "schema_version": 1,
            "policies": [
                {
                    "family": "test-family",
                    "reviewed_date": "2026-08-21",
                    "patterns": ["test-model"],
                    "exclude_patterns": ["coder", "embedding"],
                    "verified": True,
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "min_p": None,
                    "thinking": True,
                    "extra": {},
                    "source_url": "https://example.com/model-card",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policies.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            included = resolve_policy("vendor", "test-model-8b", policy_file=path)
            with self.assertWarnsRegex(RuntimeWarning, "falling back to strict"):
                excluded = resolve_policy("vendor", "test-model-coder-8b", policy_file=path)

        self.assertEqual(included.name, "vendor")
        self.assertEqual(excluded.name, "strict")
        self.assertEqual(excluded.source, "unknown-model-fallback")

    def test_reviewed_catalog_does_not_claim_unreviewed_sibling_types(self):
        from sixcat.policy import resolve_policy

        unreviewed = (
            "Qwen3-Coder-480B-A35B-Instruct",
            "Qwen3-Embedding-8B",
            "Qwen3-Reranker-8B",
            "Qwen2.5-VL-72B-Instruct",
            "Qwen/Qwen2.5-32B",
            "Llama-3.2-11B-Vision-Instruct",
            "Meta-Llama-3.1-8B",
            "DeepSeek-V4-Flash-Base",
            "DeepSeek-V3.2-Speciale",
            "MiniMax-Text-01",
            "gemma-4-31b-pt",
        )
        for model in unreviewed:
            with self.subTest(model=model), self.assertWarnsRegex(RuntimeWarning, "falling back to strict"):
                policy = resolve_policy("vendor", model)
            self.assertEqual(policy.name, "strict")
            self.assertEqual(policy.source, "unknown-model-fallback")

    def test_policy_file_rejects_https_source_url_without_hostname(self):
        self._assert_invalid_policy_entry("source_url", "https:///missing-host", "source_url")

    def test_strict_is_greedy_no_think_with_phase3_budgets(self):
        from sixcat.policy import strict_policy

        policy = strict_policy({"math": 640}, seed=None)

        self.assertEqual(policy.name, "strict")
        self.assertEqual(policy.temperature, 0.0)
        self.assertFalse(policy.thinking)
        self.assertEqual(policy.budgets["knowledge"], 768)
        self.assertEqual(policy.budgets["math"], 640)
        self.assertEqual(policy.source, "builtin-strict")

    def test_measured_zero_truncation_thinking_defaults_and_derivation(self):
        import math

        from sixcat.policy import THINKING_BUDGETS

        # Seed-1 uncensored vendor calibration receipts. Formula minimum is
        # max(starting thinking table, ceil(2 * p95)).
        starting = {
            "knowledge": 768,
            "math": 2048,
            "truth": 768,
            "instruct": 1024,
            "code": 3072,
            "tools": 768,
        }
        measured_p95 = {
            "knowledge": 798.15,
            "math": 433.6,
            "truth": 881.15,
            "instruct": 3383.25,
            "code": 742.4,
            "tools": 72.85,
        }
        observed_max = {
            "knowledge": 1546,
            "math": 635,
            "truth": 1891,
            "instruct": 3521,
            "code": 883,
            "tools": 89,
        }
        formula_minima = {
            category: max(starting[category], math.ceil(2 * measured_p95[category]))
            for category in starting
        }
        self.assertEqual(
            formula_minima,
            {
                "knowledge": 1597,
                "math": 2048,
                "truth": 1763,
                "instruct": 6767,
                "code": 3072,
                "tools": 768,
            },
        )

        # Zero truncation is an acceptance requirement, so apply observed_max+1 to
        # every category. Only truth changes: its formula minimum is below the
        # observed uncensored max, and 1763 would re-truncate deterministic tqa:19.
        expected = {
            category: max(formula_minima[category], observed_max[category] + 1)
            for category in formula_minima
        }
        self.assertEqual(
            expected,
            {
                "knowledge": 1597,
                "math": 2048,
                "truth": 1892,
                "instruct": 6767,
                "code": 3072,
                "tools": 768,
            },
        )
        self.assertEqual(THINKING_BUDGETS, expected)

    def test_reviewed_vendor_mappings_resolve_qwen_and_ornith(self):
        from sixcat.policy import resolve_policy

        qwen = resolve_policy("vendor", "Qwen3.8-27B-Q4_K_M", seed=2)
        ornith = resolve_policy("vendor", "ornith-nomtp", seed=3)

        self.assertEqual(
            (qwen.name, qwen.temperature, qwen.top_p, qwen.top_k, qwen.min_p, qwen.thinking),
            ("vendor", 1.0, 0.95, 20, 0.0, True),
        )
        self.assertEqual(qwen.extra["seed"], 2)
        self.assertIn("huggingface.co/Qwen/Qwen3.8-27B", qwen.source)
        self.assertEqual(
            (ornith.name, ornith.temperature, ornith.top_p, ornith.top_k, ornith.min_p, ornith.thinking),
            ("vendor", 0.6, 0.95, 20, None, True),
        )
        self.assertEqual(ornith.extra["seed"], 3)
        self.assertIn("huggingface.co/ornith-ai/Ornith-1.5-35B-A3B", ornith.source)
        expected_budgets = {
            "knowledge": 1597,
            "math": 2048,
            "truth": 1892,
            "instruct": 6767,
            "code": 3072,
            "tools": 768,
        }
        self.assertEqual(dict(qwen.budgets), expected_budgets)
        self.assertEqual(dict(ornith.budgets), expected_budgets)

    def test_vendor_catalog_resolves_published_families(self):
        from sixcat.policy import resolve_policy

        cases = (
            ("Qwen3.6-35B-A3B", 1.0, 0.95, 20, 0.0, True, "Qwen/Qwen3.6-35B-A3B"),
            ("Qwen3.5-27B", 1.0, 0.95, 20, 0.0, True, "Qwen/Qwen3.5-35B-A3B"),
            ("Qwen3-Next-80B-A3B-Thinking", 0.6, 0.95, 20, 0.0, True, "Qwen3-Next-80B-A3B-Thinking"),
            ("Qwen3-Next-80B-A3B-Instruct", 0.7, 0.8, 20, 0.0, False, "Qwen3-Next-80B-A3B-Instruct"),
            ("Qwen3-32B", 0.6, 0.95, 20, 0.0, True, "Qwen/Qwen3-32B"),
            ("Qwen2.5-32B-Instruct", 0.7, 0.8, 20, None, False, "Qwen2.5-32B-Instruct"),
            ("Llama-3.3-70B-Instruct", 0.6, 0.9, None, None, False, "Llama-3.3-70B-Instruct"),
            ("DeepSeek-V4-Flash-0731", 1.0, 0.95, None, None, True, "DeepSeek-V4-Flash-0731"),
            ("DeepSeek-V4-Flash-Vision-Exp", 1.0, 0.95, None, None, True, "api-docs.deepseek.com/updates"),
            ("DeepSeek-V4-Flash-DSpark", 1.0, 1.0, None, None, True, "DeepSeek-V4-Flash-DSpark"),
            ("DeepSeek-V4-Flash", 1.0, 1.0, None, None, True, "DeepSeek-V4-Flash"),
            ("DeepSeek-V4-Pro-0813", 1.0, 0.95, None, None, True, "DeepSeek-V4-Pro-0813"),
            ("DeepSeek-V4-Pro-DSpark", 1.0, 1.0, None, None, True, "DeepSeek-V4-Pro-DSpark"),
            ("DeepSeek-V4-Pro", 1.0, 1.0, None, None, True, "DeepSeek-V4-Pro"),
            ("DeepSeek-V3.2", 1.0, 0.95, None, None, True, "DeepSeek-V3.2"),
            ("DeepSeek-R1-0528", 0.6, 0.95, None, None, True, "DeepSeek-R1"),
            ("GLM-4.7", 1.0, 0.95, None, None, True, "GLM-4.7"),
            ("GLM-4.6", 1.0, 0.95, 40, None, True, "GLM-4.6"),
            ("Kimi-K2-Thinking", 1.0, None, None, None, True, "Kimi-K2-Thinking"),
            ("Kimi-K2-Instruct", 0.6, None, None, None, False, "Kimi-K2-Instruct"),
            ("gpt-oss-120b", 1.0, 1.0, None, None, True, "openai/gpt-oss"),
            ("MiniMax-M2.7", 1.0, 0.95, 40, None, True, "MiniMax"),
            ("gemma-4-31b-it", 1.0, 0.95, 64, None, True, "model_card_4"),
            ("Magistral-Small-2506", 0.7, 0.95, None, None, True, "Magistral-Small-2506"),
            ("NVIDIA-Nemotron-3-Ultra-550B-A55B", 1.0, 0.95, None, None, True, "nemotron-3-ultra"),
            ("NVIDIA-Nemotron-3-Nano-30B-A3B", 1.0, 1.0, None, None, True, "Nemotron-3-Nano"),
        )
        for model, temperature, top_p, top_k, min_p, thinking, source_needle in cases:
            with self.subTest(model=model):
                policy = resolve_policy("vendor", model)
                self.assertEqual(
                    (policy.name, policy.temperature, policy.top_p, policy.top_k, policy.min_p, policy.thinking),
                    ("vendor", temperature, top_p, top_k, min_p, thinking),
                )
                self.assertEqual(policy.extra["seed"], 1)
                self.assertIn(source_needle, policy.source)

    def test_vendor_specific_qwen_patterns_win_before_generic_qwen3(self):
        from sixcat.policy import resolve_policy

        qwen38 = resolve_policy("vendor", "qwen3.8-27b")
        qwen35 = resolve_policy("vendor", "qwen3.5-35b-a3b")
        next_thinking = resolve_policy("vendor", "qwen3-next-80b-a3b-thinking")
        next_instruct = resolve_policy("vendor", "qwen3-next-80b-a3b-instruct")
        qwen3 = resolve_policy("vendor", "qwen3-8b")

        self.assertEqual(qwen38.temperature, 1.0)
        self.assertIn("Qwen3.8-27B", qwen38.source)
        self.assertEqual(qwen35.temperature, 1.0)
        self.assertIn("Qwen3.5-35B-A3B", qwen35.source)
        self.assertEqual(next_thinking.temperature, 0.6)
        self.assertTrue(next_thinking.thinking)
        self.assertEqual(next_instruct.temperature, 0.7)
        self.assertFalse(next_instruct.thinking)
        self.assertEqual(qwen3.temperature, 0.6)
        self.assertIn("Qwen/Qwen3-32B", qwen3.source)

    def test_vendor_specific_deepseek_v4_patterns_win_before_generic(self):
        from sixcat.policy import resolve_policy

        flash_0731 = resolve_policy("vendor", "DeepSeek-V4-Flash-0731")
        flash_preview = resolve_policy("vendor", "DeepSeek-V4-Flash")
        flash_dspark = resolve_policy("vendor", "DeepSeek-V4-Flash-DSpark")
        vision = resolve_policy("vendor", "deepseek-v4-flash-vision-exp")
        pro_0813 = resolve_policy("vendor", "DeepSeek-V4-Pro-0813")
        pro_dspark = resolve_policy("vendor", "DeepSeek-V4-Pro-DSpark")
        pro_preview = resolve_policy("vendor", "DeepSeek-V4-Pro")

        self.assertEqual((flash_0731.temperature, flash_0731.top_p), (1.0, 0.95))
        self.assertIn("DeepSeek-V4-Flash-0731", flash_0731.source)
        self.assertEqual((flash_preview.temperature, flash_preview.top_p), (1.0, 1.0))
        self.assertIn("deepseek-ai/DeepSeek-V4-Flash", flash_preview.source)
        self.assertNotIn("0731", flash_preview.source)
        self.assertEqual((flash_dspark.temperature, flash_dspark.top_p), (1.0, 1.0))
        self.assertIn("DeepSeek-V4-Flash-DSpark", flash_dspark.source)
        self.assertEqual((vision.temperature, vision.top_p), (1.0, 0.95))
        self.assertIn("api-docs.deepseek.com/updates", vision.source)
        self.assertEqual((pro_0813.temperature, pro_0813.top_p), (1.0, 0.95))
        self.assertIn("DeepSeek-V4-Pro-0813", pro_0813.source)
        self.assertEqual((pro_dspark.temperature, pro_dspark.top_p), (1.0, 1.0))
        self.assertIn("DeepSeek-V4-Pro-DSpark", pro_dspark.source)
        self.assertEqual((pro_preview.temperature, pro_preview.top_p), (1.0, 1.0))
        self.assertIn("deepseek-ai/DeepSeek-V4-Pro", pro_preview.source)
        self.assertNotIn("0813", pro_preview.source)

    def test_vendor_catalog_entries_are_reviewed_citations(self):
        import json
        from pathlib import Path

        document = json.loads(Path("sixcat/model-policies.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(document["policies"]), 20)
        families = []
        for entry in document["policies"]:
            families.append(entry["family"])
            self.assertTrue(entry["verified"])
            self.assertRegex(entry["reviewed_date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(entry["source_url"].startswith("https://"))
            self.assertTrue(entry["patterns"])
        self.assertEqual(len(families), len(set(families)))

    def test_vendor_uses_seed_one_out_of_the_box(self):
        from sixcat.policy import resolve_policy

        qwen = resolve_policy("vendor", "Qwen3.8-27B-Q4_K_M")
        ornith = resolve_policy("vendor", "ornith-aeon-35b")

        self.assertEqual(qwen.extra["seed"], 1)
        self.assertEqual(ornith.extra["seed"], 1)

    def test_explicit_seed_overrides_vendor_default(self):
        from sixcat.policy import resolve_policy

        policy = resolve_policy("vendor", "ornith-aeon-35b", seed=0)

        self.assertEqual(policy.extra["seed"], 0)

    def test_unknown_vendor_model_loudly_falls_back_to_strict(self):
        from sixcat.policy import resolve_policy

        with self.assertWarnsRegex(RuntimeWarning, "unknown model.*falling back to strict"):
            policy = resolve_policy("vendor", "mystery-7b", seed=9)

        self.assertEqual(policy.name, "strict")
        self.assertFalse(policy.thinking)
        self.assertEqual(policy.source, "unknown-model-fallback")
        self.assertEqual(policy.extra["seed"], 9)

    def test_policy_file_requires_per_entry_reviewed_date(self):
        import json
        import tempfile
        from pathlib import Path

        from sixcat.policy import resolve_policy

        document = {
            "schema_version": 1,
            "policies": [
                {
                    "family": "test-family",
                    "patterns": ["test-model"],
                    "verified": True,
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "min_p": None,
                    "thinking": True,
                    "extra": {},
                    "source_url": "https://example.com/model-card",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policies.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewed_date"):
                resolve_policy("vendor", "test-model", policy_file=path, seed=1)

    def test_policy_file_requires_cited_https_source_url(self):
        import json
        import tempfile
        from pathlib import Path

        from sixcat.policy import resolve_policy

        document = {
            "schema_version": 1,
            "policies": [
                {
                    "family": "test-family",
                    "reviewed_date": "2026-08-20",
                    "patterns": ["test-model"],
                    "verified": True,
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "min_p": None,
                    "thinking": True,
                    "extra": {},
                    "source_url": "not-a-citation",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policies.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source_url"):
                resolve_policy("vendor", "test-model", policy_file=path, seed=1)

    def test_invalid_policy_entry_settings_fail_instead_of_falling_back(self):
        import json
        import tempfile
        from pathlib import Path

        from sixcat.policy import resolve_policy

        document = {
            "schema_version": 1,
            "policies": [
                {
                    "family": "test-family",
                    "reviewed_date": "2026-08-20",
                    "patterns": ["test-model"],
                    "verified": True,
                    "top_p": 0.95,
                    "top_k": 20,
                    "min_p": None,
                    "thinking": True,
                    "extra": {},
                    "source_url": "https://example.com/model-card",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policies.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "temperature"):
                resolve_policy("vendor", "test-model", policy_file=path, seed=1)

    def test_vendor_mapping_budgets_apply_before_cli_overrides(self):
        import json
        import tempfile
        from pathlib import Path

        from sixcat.policy import resolve_policy

        document = {
            "schema_version": 1,
            "policies": [
                {
                    "family": "test-family",
                    "reviewed_date": "2026-08-20",
                    "patterns": ["test-model"],
                    "verified": True,
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "min_p": None,
                    "thinking": True,
                    "budgets": {"math": 2304, "tools": 900},
                    "extra": {},
                    "source_url": "https://example.com/model-card",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policies.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            policy = resolve_policy(
                "vendor",
                "test-model",
                policy_file=path,
                budget_overrides={"code": 4096},
                seed=1,
            )

        self.assertEqual(policy.budgets["knowledge"], 1597)
        self.assertEqual(policy.budgets["math"], 2304)
        self.assertEqual(policy.budgets["truth"], 1892)
        self.assertEqual(policy.budgets["instruct"], 6767)
        self.assertEqual(policy.budgets["tools"], 900)
        self.assertEqual(policy.budgets["code"], 4096)

    def test_policy_file_rejects_non_boolean_thinking_setting(self):
        import json
        import tempfile
        from pathlib import Path

        from sixcat.policy import resolve_policy

        document = {
            "schema_version": 1,
            "policies": [
                {
                    "family": "test-family",
                    "reviewed_date": "2026-08-20",
                    "patterns": ["test-model"],
                    "verified": True,
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "min_p": None,
                    "thinking": "false",
                    "extra": {},
                    "source_url": "https://example.com/model-card",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policies.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "thinking"):
                resolve_policy("vendor", "test-model", policy_file=path, seed=1)


class TestPolicyAwareClient(unittest.TestCase):
    def test_client_sends_resolved_policy_and_records_exact_params(self):
        import json
        from unittest.mock import patch

        from sixcat.client import ChatClient
        from sixcat.policy import Policy

        policy = Policy(
            name="vendor",
            temperature=0.6,
            top_p=0.95,
            top_k=20,
            min_p=0.0,
            thinking=True,
            budgets={"math": 2048},
            extra={"seed": 7, "presence_penalty": 0.0},
            source="test",
        )
        response_body = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "391", "reasoning_content": "17*23=391"},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 12},
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(response_body).encode("utf-8")

        captured = {}

        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = ChatClient("http://localhost:9999/v1", "model", policy, api_key="key").complete(
                "probe", max_tokens=99
            )

        self.assertEqual(captured["temperature"], 0.6)
        self.assertEqual(captured["top_p"], 0.95)
        self.assertEqual(captured["top_k"], 20)
        self.assertEqual(captured["min_p"], 0.0)
        self.assertEqual(captured["seed"], 7)
        self.assertEqual(captured["presence_penalty"], 0.0)
        self.assertEqual(captured["chat_template_kwargs"], {"enable_thinking": True})
        self.assertEqual(out["request_params"]["max_tokens"], 99)
        self.assertEqual(out["request_params"]["enable_thinking"], True)
        self.assertEqual(out["reasoning_content"], "17*23=391")

    def test_policy_extra_cannot_override_protected_request_fields(self):
        from sixcat.policy import Policy

        for protected in (
            "model",
            "messages",
            "max_tokens",
            "temperature",
            "top_p",
            "top_k",
            "min_p",
            "enable_thinking",
            "chat_template_kwargs",
            "tools",
            "tool_choice",
        ):
            with self.subTest(protected=protected), self.assertRaisesRegex(ValueError, "protected"):
                Policy(
                    name="vendor",
                    temperature=0.6,
                    top_p=0.95,
                    top_k=20,
                    min_p=None,
                    thinking=True,
                    budgets={"math": 2048},
                    extra={protected: "override"},
                    source="test",
                )


class TestPolicyCliWiring(unittest.TestCase):
    def test_vendor_cli_resolves_policy_file_seed_and_budget_overrides(self):
        from pathlib import Path
        from unittest.mock import patch

        from sixcat.__main__ import main
        from sixcat.policy import strict_policy

        with (
            patch("sixcat.__main__.RunJournal") as journal_type,
            patch("sixcat.__main__.Session") as session_type,
            patch("sixcat.__main__.ChatClient") as client_type,
            patch("sixcat.__main__.resolve_policy", return_value=strict_policy(seed=42)) as resolve,
            patch("sixcat.__main__.run_battery", return_value={}) as run_battery,
            patch("sixcat.__main__.render_table", return_value="ok"),
        ):
            rc = main(
                [
                    "--model",
                    "ornith-nomtp",
                    "--policy",
                    "vendor",
                    "--policy-file",
                    "custom.json",
                    "--seed",
                    "42",
                    "--budget",
                    "math=2222",
                    "--request-timeout",
                    "900",
                    "--skip-code-exec",
                    "--log",
                    "ignored.jsonl",
                    "--no-resume",
                ]
            )

        self.assertEqual(rc, 0)
        resolve.assert_called_once_with(
            "vendor",
            "ornith-nomtp",
            budget_overrides={"math": 2222},
            seed=42,
            policy_file=Path("custom.json"),
        )
        policy = client_type.call_args.args[2]
        self.assertEqual(policy.extra["seed"], 42)
        self.assertEqual(client_type.call_args.kwargs["timeout"], 900.0)
        identity = journal_type.call_args.kwargs["identity"]
        self.assertEqual(
            identity,
            {
                "result_schema": "sixcat-v2",
                "parser": "v3",
                "model": "ornith-nomtp",
                "base_url": "http://127.0.0.1:8085/v1",
                "policy": policy.name,
                "policy_fingerprint": policy.fingerprint,
                "budgets": dict(policy.budgets),
                "limit": 20,
                "request_timeout_seconds": 900.0,
                "code_execution": "disabled",
            },
        )
        self.assertTrue(run_battery.call_args.kwargs["skip_code_exec"])
        self.assertIsNotNone(session_type.return_value)

    def test_vendor_cli_omits_seed_so_policy_default_applies(self):
        from unittest.mock import patch

        from sixcat.__main__ import main
        from sixcat.policy import resolve_policy as real_resolve

        with (
            patch("sixcat.__main__.RunJournal"),
            patch("sixcat.__main__.Session"),
            patch("sixcat.__main__.ChatClient"),
            patch("sixcat.__main__.resolve_policy", wraps=real_resolve) as resolve,
            patch("sixcat.__main__.run_battery", return_value={}),
            patch("sixcat.__main__.render_table", return_value="ok"),
        ):
            rc = main(
                [
                    "--model",
                    "ornith-aeon-35b",
                    "--policy",
                    "vendor",
                    "--log",
                    "ignored.jsonl",
                    "--no-resume",
                ]
            )

        self.assertEqual(rc, 0)
        resolve.assert_called_once_with(
            "vendor",
            "ornith-aeon-35b",
            budget_overrides=None,
            seed=None,
            policy_file=None,
        )
        policy = real_resolve(*resolve.call_args.args, **resolve.call_args.kwargs)
        self.assertEqual(policy.extra["seed"], 1)

    def test_cli_uses_sixcat_api_key_environment_default(self):
        import os
        from unittest.mock import patch

        from sixcat.__main__ import main
        from sixcat.policy import strict_policy

        with (
            patch.dict(os.environ, {"SIXCAT_API_KEY": "unit-test-key"}),
            patch("sixcat.__main__.RunJournal") as journal_type,
            patch("sixcat.__main__.Session"),
            patch("sixcat.__main__.ChatClient") as client_type,
            patch("sixcat.__main__.resolve_policy", return_value=strict_policy()),
            patch("sixcat.__main__.run_battery", return_value={}) as run_battery,
            patch("sixcat.__main__.render_table", return_value="ok"),
        ):
            rc = main(
                [
                    "--model",
                    "test-model",
                    "--log",
                    "ignored.jsonl",
                    "--no-resume",
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(client_type.call_args.kwargs["api_key"], "unit-test-key")
        self.assertFalse(run_battery.call_args.kwargs["skip_code_exec"])
        self.assertEqual(journal_type.call_args.kwargs["identity"]["code_execution"], "host-guarded")

    def test_cli_rejects_mismatched_resume_before_constructing_client(self):
        from unittest.mock import patch

        from sixcat.__main__ import main
        from sixcat.policy import strict_policy

        with (
            patch("sixcat.__main__.RunJournal", side_effect=ValueError("run identity mismatch: model")),
            patch("sixcat.__main__.ChatClient") as client_type,
            patch("sixcat.__main__.resolve_policy", return_value=strict_policy()),
        ):
            with self.assertRaises(SystemExit) as caught:
                main(["--model", "test-model", "--log", "existing.jsonl"])

        self.assertEqual(caught.exception.code, 2)
        client_type.assert_not_called()


class TestPolicyProbe(unittest.TestCase):
    class FakeClient:
        def __init__(self, policy, response):
            self.policy = policy
            self.response = response
            self.calls = []

        def complete(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            return dict(self.response)

    def test_no_think_accepts_answer_with_empty_reasoning(self):
        from sixcat.policy import probe_policy, strict_policy

        client = self.FakeClient(
            strict_policy(),
            {"text": "391", "reasoning_content": "", "finish": "stop", "usage": {"completion_tokens": 2}},
        )

        probe = probe_policy(client)

        self.assertEqual(probe["status"], "ok")
        self.assertEqual(probe["reasoning_chars"], 0)
        self.assertEqual(len(client.calls), 1)

    def test_thinking_requires_reasoning_even_if_answer_is_correct(self):
        from sixcat.policy import Policy, probe_policy

        policy = Policy("vendor", 0.6, 0.95, 20, None, True, {"math": 2048}, {}, "test")
        client = self.FakeClient(
            policy,
            {"text": "391", "reasoning_content": "", "finish": "stop", "usage": {"completion_tokens": 2}},
        )

        probe = probe_policy(client)

        self.assertEqual(probe["status"], "failed")
        self.assertIn("thinking requested", probe["reason"])

    def test_thinking_accepts_dedicated_or_inline_reasoning(self):
        from sixcat.policy import Policy, probe_policy

        policy = Policy("vendor", 0.6, 0.95, 20, None, True, {"math": 2048}, {}, "test")
        for response in (
            {"text": "391", "reasoning_content": "17 * 23 = 391", "finish": "stop", "usage": {}},
            {"text": "<think>17 * 23 = 391</think>391", "reasoning_content": "", "finish": "stop", "usage": {}},
        ):
            with self.subTest(response=response):
                self.assertEqual(probe_policy(self.FakeClient(policy, response))["status"], "ok")

    def test_no_think_fails_when_reasoning_is_inlined(self):
        from sixcat.policy import probe_policy, strict_policy

        response = {
            "text": "<think>17 * 23 = 391</think>391",
            "reasoning_content": "",
            "finish": "stop",
            "usage": {},
        }
        probe = probe_policy(self.FakeClient(strict_policy(), response))

        self.assertEqual(probe["status"], "failed")
        self.assertIn("thinking disabled", probe["reason"])

    def test_no_think_fails_on_any_dedicated_reasoning(self):
        from sixcat.policy import probe_policy, strict_policy

        response = {
            "text": "391",
            "reasoning_content": "x",
            "finish": "stop",
            "usage": {},
        }
        probe = probe_policy(self.FakeClient(strict_policy(), response))

        self.assertEqual(probe["status"], "failed")
        self.assertEqual(probe["reasoning_chars"], 1)
        self.assertIn("thinking disabled", probe["reason"])


class TestPolicyRunIntegration(unittest.TestCase):
    class FakeClient:
        def __init__(self, policy, response):
            self.policy = policy
            self.response = response
            self.model = "ornith-test"
            self.base_url = "http://localhost/v1"
            self.api_key = "none"

        def complete(self, prompt, **kwargs):
            return dict(self.response)

    def test_run_output_carries_resolved_policy_probe_and_fingerprint(self):
        from unittest.mock import patch

        from sixcat.policy import strict_policy
        from sixcat.run import run_battery

        policy = strict_policy({"knowledge": 600})
        client = self.FakeClient(
            policy,
            {"text": "391", "reasoning_content": "", "finish": "stop", "usage": {"completion_tokens": 2}},
        )
        rows = [{"ok": True, "finish": "stop", "ctok": 2, "parse_confidence": "high"}]
        with (
            patch("sixcat.run.fetch_server_props", return_value={"source": "test"}),
            patch("sixcat.run.run_knowledge", return_value=rows),
            patch("sixcat.run.run_math", return_value=rows),
            patch("sixcat.run.run_truth", return_value=rows),
            patch("sixcat.run.run_instruct", return_value=rows),
            patch("sixcat.run.run_code", return_value=rows),
            patch("sixcat.run.run_tools", return_value=rows),
        ):
            result = run_battery(client, limit=1, skip_code_exec=False)

        self.assertEqual(result["policy"], policy.to_dict())
        self.assertEqual(result["policy_source"], "builtin-strict")
        self.assertEqual(result["policy_probe"], "ok")
        self.assertEqual(result["policy_fingerprint"], policy.fingerprint)
        self.assertEqual(result["budgets"]["knowledge"], 600)
        self.assertEqual(result["parser"], "v3")
        self.assertEqual(result["code_execution"], "host-guarded")
        self.assertNotIn("code-exec-disabled", result["overall_flags"])
        self.assertEqual(result["overall"], {"policy": "strict", "score": 100.0})

        from sixcat.run import render_table

        table = render_table(result)
        self.assertIn("policy: strict", table)
        self.assertIn("code execution: host-guarded", table)
        self.assertIn("overall[strict]", table)

    def test_failed_thinking_probe_aborts_before_first_category(self):
        from unittest.mock import patch

        from sixcat.policy import Policy
        from sixcat.run import run_battery

        policy = Policy("vendor", 0.6, 0.95, 20, None, True, {"knowledge": 768}, {}, "test")
        client = self.FakeClient(
            policy,
            {"text": "391", "reasoning_content": "", "finish": "stop", "usage": {}},
        )
        with (
            patch("sixcat.run.fetch_server_props", return_value={"source": "test"}),
            patch("sixcat.run.run_knowledge") as run_knowledge,
            self.assertRaisesRegex(RuntimeError, "policy probe failed"),
        ):
            run_battery(client, limit=1)
        run_knowledge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
