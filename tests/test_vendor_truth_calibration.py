from __future__ import annotations

import unittest


class TestTruthBudgetDerivation(unittest.TestCase):
    def test_uses_ceil_of_twice_uncensored_p95_with_thinking_table_floor(self):
        from tools.calibrate_vendor_truth import derive_recommendation

        derived = derive_recommendation(
            {
                "truncated": 0,
                "ctok_p95": 863.4,
                "ctok_max": 1536,
            },
            starting_budget=768,
        )

        self.assertEqual(derived["ceil_2xp95"], 1727)
        self.assertEqual(derived["recommended_truth_budget"], 1727)
        self.assertEqual(derived["starting_thinking_budget"], 768)

    def test_zero_truncation_acceptance_uses_observed_max_plus_one_floor(self):
        from tools.calibrate_vendor_truth import derive_recommendation

        derived = derive_recommendation(
            {
                "truncated": 0,
                "ctok_p95": 881.15,
                "ctok_max": 1891,
            },
            starting_budget=768,
            require_zero_truncation_floor=True,
        )

        self.assertEqual(derived["ceil_2xp95"], 1763)
        self.assertEqual(derived["zero_truncation_floor"], 1892)
        self.assertEqual(derived["recommended_truth_budget"], 1892)

    def test_acceptance_reports_the_exact_truncated_truth_row(self):
        from tools.calibrate_vendor_truth import acceptance_errors

        rows = [
            {
                "cat": "truth",
                "key": f"tqa:{index}",
                "id": f"tqa:{index}",
                "ok": True,
                "pred": "A",
                "gold": "A",
                "finish": "length" if index == 19 else "stop",
                "ctok": 3072 if index == 19 else 100,
                "ptok": 50,
                "request_params": {
                    "temperature": 0.6,
                    "max_tokens": 3072,
                    "enable_thinking": True,
                    "top_p": 0.95,
                    "top_k": 20,
                    "seed": 1,
                },
                "parse_confidence": "high",
                "raw_text": "A",
                "reasoning_content": "reasoning",
            }
            for index in range(20)
        ]
        result = {
            "rows": rows,
            "timed_out": False,
            "budget": 3072,
            "category_stats": {
                "n": 20,
                "truncated": 1,
                "parse_confidence_missing": 0,
            },
        }

        errors = acceptance_errors(result)

        self.assertIn("truncated rows: truth/tqa:19", errors)


if __name__ == "__main__":
    unittest.main()
