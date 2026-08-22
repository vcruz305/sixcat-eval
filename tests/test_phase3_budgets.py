from __future__ import annotations

import math
import unittest


class TestBudgetOverrides(unittest.TestCase):
    def test_valid_overrides_parse(self):
        from sixcat.__main__ import parse_budget_overrides

        self.assertEqual(
            parse_budget_overrides(["math=2048", " code=3072 "]),
            {"math": 2048, "code": 3072},
        )

    def test_unknown_category_is_rejected(self):
        from sixcat.__main__ import parse_budget_overrides

        with self.assertRaisesRegex(ValueError, "unknown category"):
            parse_budget_overrides(["latency=10"])

    def test_non_integer_is_rejected(self):
        from sixcat.__main__ import parse_budget_overrides

        with self.assertRaisesRegex(ValueError, "not an integer"):
            parse_budget_overrides(["math=many"])

    def test_non_positive_is_rejected(self):
        from sixcat.__main__ import parse_budget_overrides

        for value in ("0", "-1"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "positive integer"):
                parse_budget_overrides([f"math={value}"])

    def test_missing_equals_is_rejected(self):
        from sixcat.__main__ import parse_budget_overrides

        with self.assertRaisesRegex(ValueError, "CATEGORY=N"):
            parse_budget_overrides(["math"])


class TestMeasuredDefaults(unittest.TestCase):
    def test_strict_no_think_budget_derivation_receipt(self):
        from sixcat.policy import strict_policy
        from sixcat.run import DEFAULT_BUDGETS

        # Fresh uncensored calibrations measured instruct p95=640.1 on Ornith and
        # strict-math p95=598.0 on Qwen3.8. The latter was added after Phase 6
        # exposed two Qwen math truncations at the previous shared 512-token cap.
        # The plan requires max(starting budget, ceil(2 * uncensored p95)).
        derived_math_budget = math.ceil(2 * 598.0000000000001)
        derived_instruct_budget = math.ceil(2 * 640.1)
        expected = {
            "knowledge": 768,
            "math": derived_math_budget,
            "truth": 64,
            "instruct": derived_instruct_budget,
            "code": 1024,
            "tools": 256,
        }

        policy = strict_policy(seed=0)
        self.assertFalse(policy.thinking)
        self.assertEqual(derived_math_budget, 1197)
        self.assertEqual(derived_instruct_budget, 1281)
        self.assertEqual(dict(policy.budgets), expected)
        self.assertEqual(DEFAULT_BUDGETS, expected)


class TestPhase3CliWiring(unittest.TestCase):
    def test_main_uses_strict_no_think_policy_and_default_budgets(self):
        from unittest.mock import patch

        from sixcat.__main__ import main

        with (
            patch("sixcat.__main__.RunJournal") as journal_type,
            patch("sixcat.__main__.Session") as session_type,
            patch("sixcat.__main__.ChatClient") as client_type,
            patch("sixcat.__main__.run_battery", return_value={}) as run_battery,
            patch("sixcat.__main__.render_table", return_value="ok"),
        ):
            rc = main(["--model", "ornith-nomtp", "--log", "ignored.jsonl", "--no-resume"])

        self.assertEqual(rc, 0)
        client_args = client_type.call_args.args
        self.assertEqual(len(client_args), 3)
        policy = client_args[2]
        self.assertEqual(policy.name, "strict")
        self.assertFalse(policy.thinking)
        self.assertEqual(policy.budgets["knowledge"], 768)
        run_battery.assert_called_once_with(
            client_type.return_value,
            limit=20,
            session=session_type.return_value,
            skip_code_exec=False,
        )
        journal_type.return_value.close.assert_called_once_with()


class TestTruncationFlags(unittest.TestCase):
    def test_flags_name_each_unreliable_category(self):
        from sixcat.run import build_overall_flags

        stats = {
            "knowledge": {
                "n": 20,
                "truncated": 1,
                "parse_high_confidence": 20,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 0,
                "parse_confidence_missing": 0,
            },
            "math": {
                "n": 20,
                "truncated": 0,
                "parse_high_confidence": 15,
                "parse_low_confidence": 5,
                "parse_confidence_not_applicable": 0,
                "parse_confidence_missing": 0,
            },
            "truth": {
                "n": 20,
                "truncated": 0,
                "parse_high_confidence": 20,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 0,
                "parse_confidence_missing": 0,
            },
            "instruct": {
                "n": 20,
                "truncated": 0,
                "parse_high_confidence": 0,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 20,
                "parse_confidence_missing": 0,
            },
            "code": {
                "n": 20,
                "truncated": 0,
                "parse_high_confidence": 0,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 20,
                "parse_confidence_missing": 0,
            },
            "tools": {
                "n": 20,
                "truncated": 0,
                "parse_high_confidence": 0,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 20,
                "parse_confidence_missing": 0,
            },
        }

        self.assertEqual(
            build_overall_flags(stats),
            ["truncated:knowledge", "low-confidence-parses:math"],
        )


if __name__ == "__main__":
    unittest.main()
