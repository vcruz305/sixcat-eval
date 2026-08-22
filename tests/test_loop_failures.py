from __future__ import annotations

import unittest


def _looped_reasoning(times: int = 12) -> str:
    phrase = "he only wanted to eat food that was healthy and nothing else. "
    return phrase * times


def _unique_ramble(words: int = 400) -> str:
    return " ".join(f"clause{index} analysis continues without repeating" for index in range(words))


class TestLoopFailureDetection(unittest.TestCase):
    def test_failed_repeated_phrase_is_a_loop_failure(self):
        from sixcat.score import is_loop_failure

        row = {
            "ok": False,
            "finish": "length",
            "pred": "",
            "reasoning_content": _looped_reasoning(),
        }

        self.assertTrue(is_loop_failure(row))

    def test_failed_long_unique_reasoning_is_not_a_loop(self):
        from sixcat.score import is_loop_failure

        row = {
            "ok": False,
            "finish": "length",
            "pred": "",
            "reasoning_content": _unique_ramble(),
        }

        self.assertFalse(is_loop_failure(row))

    def test_passed_row_is_never_a_loop_failure(self):
        from sixcat.score import is_loop_failure

        row = {
            "ok": True,
            "finish": "stop",
            "pred": "B",
            "reasoning_content": _looped_reasoning(),
        }

        self.assertFalse(is_loop_failure(row))

    def test_emitted_row_records_loop_flag_for_failed_repeats(self):
        from sixcat.run import _row

        row = _row(
            {
                "finish": "length",
                "usage": {"completion_tokens": 8192, "prompt_tokens": 40},
                "request_params": {"max_tokens": 8192},
                "reasoning_content": _looped_reasoning(),
                "text": "",
            },
            ok=False,
            pred="",
        )

        self.assertTrue(row["loop"])
        self.assertFalse(
            _row(
                {
                    "finish": "stop",
                    "usage": {"completion_tokens": 80, "prompt_tokens": 40},
                    "request_params": {"max_tokens": 256},
                    "reasoning_content": _unique_ramble(),
                    "text": "A",
                },
                ok=True,
                pred="A",
            )["loop"]
        )


class TestCategoryLoopCounts(unittest.TestCase):
    def test_category_stats_counts_only_failed_loops(self):
        from sixcat.score import category_stats

        stats = category_stats(
            [
                {"ok": True, "finish": "stop", "ctok": 80, "reasoning_content": _looped_reasoning()},
                {"ok": False, "finish": "length", "ctok": 8192, "pred": "", "reasoning_content": _looped_reasoning()},
                {"ok": False, "finish": "length", "ctok": 8192, "pred": "", "reasoning_content": _unique_ramble()},
                {"ok": False, "finish": "stop", "ctok": 300, "pred": "C", "reasoning_content": _looped_reasoning(10)},
            ]
        )

        self.assertEqual(stats["n"], 4)
        self.assertEqual(stats["truncated"], 2)
        self.assertEqual(stats["loop_failures"], 2)


class TestLoopReporting(unittest.TestCase):
    def test_overall_flags_name_categories_with_loop_failures(self):
        from sixcat.run import CATEGORIES, build_overall_flags

        stats = {
            category: {
                "n": 20,
                "truncated": 0,
                "loop_failures": 0,
                "parse_high_confidence": 20,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 0,
                "parse_confidence_missing": 0,
            }
            for category in CATEGORIES
        }
        stats["truth"]["loop_failures"] = 3
        stats["knowledge"]["truncated"] = 1

        self.assertEqual(
            build_overall_flags(stats),
            ["truncated:knowledge", "loop-failures:truth"],
        )

    def test_render_table_prints_loop_count_per_category(self):
        from sixcat.run import CATEGORIES, render_table

        stats = {
            category: {
                "n": 2,
                "truncated": 0,
                "loop_failures": 0,
                "parse_high_confidence": 2,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 0,
                "parse_confidence_missing": 0,
            }
            for category in CATEGORIES
        }
        stats["truth"]["loop_failures"] = 2
        result = {
            "model": "fixture",
            "base_url": "fixture://",
            "policy": {"name": "vendor"},
            "policy_source": "fixture",
            "policy_fingerprint": "deadbeef",
            "categories": {category: 50.0 for category in CATEGORIES},
            "n": {category: 2 for category in CATEGORIES},
            "stats": stats,
            "overall": {"policy": "vendor", "score": 50.0},
            "overall_flags": ["loop-failures:truth"],
        }

        table = render_table(result)

        self.assertIn("loops", table)
        self.assertRegex(table, r"truth\s+50\.0\s+2\s+0\s+2\b")
        self.assertIn("loop-failures:truth", table)
