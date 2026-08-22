from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TestCurrentResultSchema(unittest.TestCase):
    def test_run_result_has_parser_v3_policy_provenance_and_labelled_overall(self):
        from sixcat.policy import strict_policy
        from sixcat.run import CATEGORIES, run_battery

        policy = strict_policy(seed=7)
        client = SimpleNamespace(
            policy=policy,
            model="fixture-model",
            base_url="http://fixture/v1",
            api_key="none",
            complete=lambda *args, **kwargs: {
                "text": "391",
                "reasoning_content": "",
                "finish": "stop",
                "usage": {"completion_tokens": 1},
            },
        )
        rows = [{"ok": True, "finish": "stop", "ctok": 1, "parse_confidence": "high"}]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("sixcat.run.fetch_server_props", return_value={"source": "fixture"}))
            for category in CATEGORIES:
                stack.enter_context(patch(f"sixcat.run.run_{category}", return_value=rows))
            result = run_battery(client, limit=1, skip_code_exec=False)

        self.assertEqual(result["parser"], "v4")
        self.assertEqual(result["result_schema"], "sixcat-v2")
        self.assertEqual(result["code_execution"], "host-guarded")
        for key in ("policy", "policy_source", "policy_probe", "policy_fingerprint", "budgets"):
            with self.subTest(key=key):
                self.assertIn(key, result)
        self.assertEqual(result["overall"], {"policy": "strict", "score": 100.0})
        self.assertEqual(result["overall_label"], "overall[strict]")
        self.assertEqual(result["overall_flags"], [])
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertIn("truncated", result["stats"][category])
                self.assertIn("parse_low_confidence", result["stats"][category])


class TestOverallFlagBoundaries(unittest.TestCase):
    @staticmethod
    def _empty_stats():
        from sixcat.run import CATEGORIES

        return {
            category: {
                "n": 10,
                "truncated": 0,
                "parse_high_confidence": 10,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 0,
                "parse_confidence_missing": 0,
            }
            for category in CATEGORIES
        }

    def test_exactly_twenty_percent_low_confidence_is_not_flagged(self):
        from sixcat.run import build_overall_flags

        stats = self._empty_stats()
        stats["math"]["parse_high_confidence"] = 8
        stats["math"]["parse_low_confidence"] = 2

        self.assertEqual(build_overall_flags(stats), [])

    def test_multiple_categories_and_reasons_are_all_flagged_deterministically(self):
        from sixcat.run import build_overall_flags

        stats = self._empty_stats()
        stats["knowledge"]["truncated"] = 1
        stats["math"]["truncated"] = 2
        stats["truth"]["parse_high_confidence"] = 7
        stats["truth"]["parse_low_confidence"] = 3
        stats["tools"]["parse_high_confidence"] = 0
        stats["tools"]["parse_low_confidence"] = 10

        self.assertEqual(
            build_overall_flags(stats),
            [
                "truncated:knowledge",
                "truncated:math",
                "low-confidence-parses:truth",
                "low-confidence-parses:tools",
            ],
        )

    def test_rendered_topline_visibly_lists_all_flags(self):
        from sixcat.run import CATEGORIES, render_table

        result = {
            "model": "fixture-model",
            "base_url": "fixture://",
            "policy": {"name": "strict"},
            "policy_source": "fixture-source",
            "policy_fingerprint": "fixture-fp",
            "categories": {category: 50.0 for category in CATEGORIES},
            "stats": {
                category: {"truncated": int(category == "knowledge"), "parse_low_confidence": 0}
                for category in CATEGORIES
            },
            "n": {category: 10 for category in CATEGORIES},
            "overall": {"policy": "strict", "score": 50.0},
            "overall_label": "overall[strict]",
            "overall_flags": ["truncated:knowledge", "low-confidence-parses:math"],
            "timed_out": False,
        }

        topline = next(line for line in render_table(result).splitlines() if line.startswith("overall["))
        self.assertIn("overall[strict]", topline)
        self.assertIn("truncated:knowledge", topline)
        self.assertIn("low-confidence-parses:math", topline)
        self.assertNotRegex(topline, r"^overall\s")


class TestBothPolicyDeltaTable(unittest.TestCase):
    @staticmethod
    def _result(name: str, fingerprint: str, source: str, scores: dict):
        from sixcat.run import CATEGORIES

        categories = {category: 10.0 for category in CATEGORIES}
        categories.update(scores)
        stats = {
            category: {"n": 2, "truncated": 0, "parse_low_confidence": 0}
            for category in CATEGORIES
        }
        stats["truth"]["truncated"] = 1 if name == "vendor" else 0
        overall_score = 20.0 if name == "strict" else 30.0
        flags = ["truncated:truth"] if name == "vendor" else []
        return {
            "model": "fixture-model",
            "policy": {"name": name},
            "policy_source": source,
            "policy_fingerprint": fingerprint,
            "parser": "v2",
            "categories": categories,
            "stats": stats,
            "n": {category: 2 for category in CATEGORIES},
            "overall": {"policy": name, "score": overall_score},
            "overall_label": f"overall[{name}]",
            "overall_flags": flags,
        }

    def test_combined_table_labels_profiles_and_calculates_vendor_minus_strict(self):
        from sixcat.report import render_both_table

        strict = self._result("strict", "strict-fp", "builtin-strict", {"knowledge": 25.0})
        vendor = self._result("vendor", "vendor-fp", "reviewed-vendor", {"knowledge": 50.0})

        table = render_both_table(strict, vendor)

        self.assertIn("strict: strict fp=strict-fp source=builtin-strict", table)
        self.assertIn("vendor: vendor fp=vendor-fp source=reviewed-vendor", table)
        knowledge = next(line for line in table.splitlines() if line.startswith("knowledge"))
        self.assertIn("25.0", knowledge)
        self.assertIn("50.0", knowledge)
        self.assertIn("+25.0", knowledge)
        self.assertIn("overall[strict→vendor]", table)
        self.assertIn("truncated:truth", table)
        self.assertNotRegex(table, r"(?m)^overall\s")

    def test_missing_score_produces_na_delta_instead_of_fabricated_zero(self):
        from sixcat.report import render_both_table

        strict = self._result("strict", "strict-fp", "builtin-strict", {"math": None})
        vendor = self._result("vendor", "vendor-fp", "reviewed-vendor", {"math": 0.0})

        table = render_both_table(strict, vendor)
        math = next(line for line in table.splitlines() if line.startswith("math"))

        self.assertIn("n/a", math)
        self.assertIn("0.0", math)
        self.assertNotIn("+0.0", math)
        self.assertNotIn("-0.0", math)


class TestBothCliCombinedReport(unittest.TestCase):
    def test_both_cli_prints_one_combined_delta_table_after_individual_runs(self):
        from sixcat.__main__ import main
        from sixcat.run import CATEGORIES

        def make_client(base_url, model, policy, api_key="none", timeout=180.0):
            return SimpleNamespace(base_url=base_url, model=model, policy=policy, api_key=api_key)

        def result_for(client, *args, **kwargs):
            policy = client.policy
            return {
                "model": client.model,
                "base_url": client.base_url,
                "policy": policy.to_dict(),
                "policy_source": policy.source,
                "policy_probe": "ok",
                "policy_fingerprint": policy.fingerprint,
                "budgets": dict(policy.budgets),
                "parser": "v2",
                "categories": {category: 50.0 for category in CATEGORIES},
                "stats": {
                    category: {"n": 1, "truncated": 0, "parse_low_confidence": 0}
                    for category in CATEGORIES
                },
                "overall": {"policy": policy.name, "score": 50.0},
                "overall_label": f"overall[{policy.name}]",
                "overall_flags": [],
                "n": {category: 1 for category in CATEGORIES},
                "items": {category: [] for category in CATEGORIES},
            }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stdout = io.StringIO()
            with (
                patch("sixcat.__main__.RunJournal"),
                patch("sixcat.__main__.Session"),
                patch("sixcat.__main__.ChatClient", side_effect=make_client),
                patch("sixcat.__main__.run_battery", side_effect=result_for),
                patch("sixcat.__main__.render_table", side_effect=lambda result: f"individual-{result['policy']['name']}"),
                patch("sixcat.__main__.render_both_table", return_value="COMBINED-DELTA") as combined,
                contextlib.redirect_stdout(stdout),
            ):
                rc = main(
                    [
                        "--model",
                        "ornith-nomtp",
                        "--policy",
                        "both",
                        "--out",
                        str(root / "both.json"),
                        "--log",
                        str(root / "both.jsonl"),
                        "--no-resume",
                    ]
                )

        self.assertEqual(rc, 0)
        combined.assert_called_once()
        strict_result, vendor_result = combined.call_args.args
        self.assertEqual(strict_result["policy"]["name"], "strict")
        self.assertEqual(vendor_result["policy"]["name"], "vendor")
        output = stdout.getvalue()
        self.assertIn("individual-strict", output)
        self.assertIn("individual-vendor", output)
        self.assertIn("COMBINED-DELTA", output)
        self.assertGreater(output.index("COMBINED-DELTA"), output.index("individual-vendor"))


if __name__ == "__main__":
    unittest.main()
