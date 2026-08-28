from __future__ import annotations

import unittest

from sixcat.policy import TASK_CEILINGS, THINKING_BUDGETS, resolve_policy
from sixcat.run import render_table
from sixcat.score import answer_tokens, category_stats, is_trunc_in_think


class TestAnswerTokenSplit(unittest.TestCase):
    def test_atok_is_ctok_minus_rtok(self):
        self.assertEqual(answer_tokens(1597, 1590), 7)

    def test_atok_none_when_engine_omits_rtok(self):
        self.assertIsNone(answer_tokens(1597, None))

    def test_atok_never_negative(self):
        self.assertEqual(answer_tokens(10, 80), 0)


class TestTruncInThink(unittest.TestCase):
    def test_length_and_empty_answer_with_reasoning_is_trunc_in_think(self):
        row = {
            "finish": "length",
            "raw_text": "",
            "pred": "",
            "reasoning_content": "the answer is B. " * 20,
            "ok": False,
        }
        self.assertTrue(is_trunc_in_think(row))

    def test_length_with_visible_answer_is_not_trunc_in_think(self):
        row = {
            "finish": "length",
            "raw_text": "B",
            "pred": "B",
            "reasoning_content": "because...",
            "ok": True,
        }
        self.assertFalse(is_trunc_in_think(row))


class TestCategoryTokenStats(unittest.TestCase):
    def test_stats_include_rtok_atok_and_trunc_in_think(self):
        rows = [
            {
                "ok": False,
                "finish": "length",
                "raw_text": "",
                "pred": "",
                "reasoning_content": "still thinking",
                "ctok": 1597,
                "rtok": 1597,
                "atok": 0,
                "parse_confidence": "low",
            },
            {
                "ok": True,
                "finish": "stop",
                "raw_text": "A",
                "pred": "A",
                "reasoning_content": "short",
                "ctok": 80,
                "rtok": 70,
                "atok": 10,
                "parse_confidence": "high",
            },
        ]
        stats = category_stats(rows)
        self.assertEqual(stats["trunc_in_think"], 1)
        self.assertEqual(stats["empty_answer"], 1)
        self.assertEqual(stats["rtok_sum"], 1667)
        self.assertEqual(stats["atok_sum"], 10)


class TestThinkingCeilingsAreTaskShaped(unittest.TestCase):
    def test_vendor_glm_thinking_uses_task_ceilings_not_qwen_p95(self):
        policy = resolve_policy("vendor", "GLM-5.3-Flash-Q2_K", family="glm-5.x")
        self.assertTrue(policy.thinking)
        self.assertEqual(dict(policy.budgets), TASK_CEILINGS)
        self.assertGreater(policy.budgets["knowledge"], THINKING_BUDGETS["knowledge"])

    def test_legacy_thinking_table_remains_documented(self):
        self.assertEqual(THINKING_BUDGETS["knowledge"], 1597)


class TestScoreTableTokenColumns(unittest.TestCase):
    def test_render_table_prints_rtok_atok(self):
        result = {
            "model": "GLM-5.3-Flash-Q2_K",
            "base_url": "http://127.0.0.1:8891/v1",
            "policy": {"name": "vendor"},
            "policy_source": "vendor:glm-5.x",
            "policy_fingerprint": "test",
            "code_execution": "host-guarded",
            "categories": {k: None for k in (
                "knowledge", "math", "truth", "instruct", "code", "tools"
            )},
            "n": {k: 0 for k in ("knowledge", "math", "truth", "instruct", "code", "tools")},
            "stats": {
                k: {
                    "n": 0,
                    "truncated": 0,
                    "loop_failures": 0,
                    "parse_high_confidence": 0,
                    "parse_low_confidence": 0,
                    "parse_confidence_not_applicable": 0,
                    "parse_confidence_missing": 0,
                    "rtok_sum": 0,
                    "atok_sum": 0,
                    "trunc_in_think": 0,
                    "empty_answer": 0,
                }
                for k in ("knowledge", "math", "truth", "instruct", "code", "tools")
            },
            "overall": {"policy": "vendor", "score": None},
        }
        result["categories"]["knowledge"] = 50.0
        result["n"]["knowledge"] = 2
        result["stats"]["knowledge"].update(
            {"n": 2, "truncated": 1, "rtok_sum": 1667, "atok_sum": 10, "trunc_in_think": 1, "empty_answer": 1}
        )
        table = render_table(result)
        self.assertIn("rtok", table.lower())
        self.assertIn("atok", table.lower())
        self.assertIn("1667", table)


if __name__ == "__main__":
    unittest.main()
