from __future__ import annotations

import unittest


class TestExtractServerTimings(unittest.TestCase):
    def test_reads_llama_cpp_prefill_and_decode_rates(self):
        from sixcat.client import extract_server_timings

        timings = extract_server_timings(
            {
                "timings": {
                    "prompt_n": 120,
                    "prompt_ms": 400.0,
                    "prompt_per_second": 300.0,
                    "predicted_n": 80,
                    "predicted_ms": 2000.0,
                    "predicted_per_second": 40.0,
                }
            }
        )

        self.assertEqual(timings["prefill_n"], 120)
        self.assertEqual(timings["decode_n"], 80)
        self.assertEqual(timings["prefill_ms"], 400.0)
        self.assertEqual(timings["decode_ms"], 2000.0)
        self.assertEqual(timings["prefill_tps"], 300.0)
        self.assertEqual(timings["decode_tps"], 40.0)

    def test_missing_timings_stay_null_instead_of_invented(self):
        from sixcat.client import extract_server_timings

        timings = extract_server_timings({"usage": {"prompt_tokens": 10, "completion_tokens": 20}})

        self.assertIsNone(timings["prefill_tps"])
        self.assertIsNone(timings["decode_tps"])
        self.assertIsNone(timings["prefill_ms"])
        self.assertIsNone(timings["decode_ms"])

    def test_reads_sglang_ttft_and_tpot(self):
        from sixcat.client import extract_server_timings

        timings = extract_server_timings(
            {
                "usage": {"prompt_tokens": 200, "completion_tokens": 50},
                "meta_info": {"ttft": 0.4, "tpot": 0.025},
            }
        )

        self.assertAlmostEqual(timings["prefill_tps"], 500.0)
        self.assertAlmostEqual(timings["decode_tps"], 40.0)
        self.assertEqual(timings["speed_source"], "sglang_meta")

    def test_stream_first_token_estimates_split_when_server_omits_timings(self):
        from sixcat.client import apply_stream_speed, extract_server_timings

        timings = apply_stream_speed(
            extract_server_timings({}),
            prompt_n=100,
            decode_n=21,
            ttft_s=0.5,
            wall_s=1.5,
        )

        self.assertAlmostEqual(timings["prefill_tps"], 200.0)
        self.assertAlmostEqual(timings["decode_tps"], 20.0)
        self.assertEqual(timings["speed_source"], "stream_ttft")

    def test_server_timings_win_over_stream_estimate(self):
        from sixcat.client import apply_stream_speed, extract_server_timings

        timings = apply_stream_speed(
            extract_server_timings(
                {"timings": {"prompt_per_second": 300.0, "predicted_per_second": 40.0}}
            ),
            prompt_n=100,
            decode_n=21,
            ttft_s=0.5,
            wall_s=1.5,
        )

        self.assertEqual(timings["prefill_tps"], 300.0)
        self.assertEqual(timings["decode_tps"], 40.0)
        self.assertEqual(timings["speed_source"], "llama_cpp_timings")


class TestSpeedRowsAndStats(unittest.TestCase):
    def test_emitted_row_copies_server_speed_fields(self):
        from sixcat.run import _row

        row = _row(
            {
                "finish": "stop",
                "usage": {"completion_tokens": 80, "prompt_tokens": 40},
                "prefill_tps": 210.5,
                "decode_tps": 24.2,
                "prefill_ms": 190.0,
                "decode_ms": 3300.0,
                "prefill_n": 40,
                "decode_n": 80,
                "text": "A",
                "reasoning_content": "",
            },
            ok=True,
            pred="A",
        )

        self.assertEqual(row["prefill_tps"], 210.5)
        self.assertEqual(row["decode_tps"], 24.2)
        self.assertEqual(row["prefill_n"], 40)
        self.assertEqual(row["decode_n"], 80)

    def test_category_stats_summarize_prefill_and_decode_rates(self):
        from sixcat.score import category_stats

        stats = category_stats(
            [
                {"ok": True, "finish": "stop", "ctok": 10, "prefill_tps": 100.0, "decode_tps": 20.0},
                {"ok": True, "finish": "stop", "ctok": 10, "prefill_tps": 300.0, "decode_tps": 40.0},
                {"ok": False, "finish": "stop", "ctok": 10},
            ]
        )

        self.assertEqual(stats["speed_n"], 2)
        self.assertEqual(stats["prefill_tps_p50"], 200.0)
        self.assertEqual(stats["decode_tps_p50"], 30.0)
        self.assertEqual(stats["prefill_tps_p95"], 290.0)
        self.assertEqual(stats["decode_tps_p95"], 39.0)


class TestSpeedTable(unittest.TestCase):
    def test_render_table_prints_median_prefill_and_decode(self):
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
                "prefill_tps_p50": None,
                "decode_tps_p50": None,
            }
            for category in CATEGORIES
        }
        stats["math"]["prefill_tps_p50"] = 180.4
        stats["math"]["decode_tps_p50"] = 22.7
        result = {
            "model": "fixture",
            "base_url": "fixture://",
            "policy": {"name": "strict"},
            "policy_source": "fixture",
            "policy_fingerprint": "deadbeef",
            "categories": {category: 50.0 for category in CATEGORIES},
            "n": {category: 2 for category in CATEGORIES},
            "stats": stats,
            "overall": {"policy": "strict", "score": 50.0},
            "overall_flags": [],
        }

        table = render_table(result)

        self.assertIn("pp", table)
        self.assertIn("tg", table)
        self.assertRegex(table, r"math\s+50\.0\s+2\s+0\s+0\s+2\s+0\s+0\s+0\s+180\.4\s+22\.7")


class TestSuiteAndCategoryWallTps(unittest.TestCase):
    def test_category_stats_average_and_suite_tps_from_per_item_wall(self):
        from sixcat.score import category_stats

        stats = category_stats(
            [
                {"ok": True, "finish": "stop", "ctok": 100, "wall_s": 2.0, "wall_tps": 50.0},
                {"ok": True, "finish": "stop", "ctok": 300, "wall_s": 3.0, "wall_tps": 100.0},
                {"ok": False, "finish": "stop", "ctok": 10},
            ]
        )

        self.assertEqual(stats["tps_n"], 2)
        self.assertEqual(stats["tps_mean"], 75.0)
        self.assertEqual(stats["total_ctok"], 400)
        self.assertEqual(stats["total_wall_s"], 5.0)
        self.assertEqual(stats["suite_tps"], 80.0)

    def test_run_battery_records_suite_tps_across_categories(self):
        import contextlib
        from types import SimpleNamespace
        from unittest.mock import patch

        from sixcat.policy import strict_policy
        from sixcat.run import CATEGORIES, run_battery

        policy = strict_policy(seed=1)
        client = SimpleNamespace(
            policy=policy,
            model="fixture-model",
            base_url="http://fixture/v1",
            api_key="none",
            complete=lambda *args, **kwargs: {
                "text": "A",
                "reasoning_content": "",
                "finish": "stop",
                "usage": {"completion_tokens": 1},
            },
        )
        rows = {
            "knowledge": [{"ok": True, "finish": "stop", "ctok": 100, "wall_s": 2.0, "wall_tps": 50.0, "parse_confidence": "high"}],
            "math": [{"ok": True, "finish": "stop", "ctok": 300, "wall_s": 3.0, "wall_tps": 100.0, "parse_confidence": "high"}],
        }
        default = [{"ok": True, "finish": "stop", "ctok": 0, "wall_s": 0.0, "wall_tps": None, "parse_confidence": "high"}]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("sixcat.run.fetch_server_props", return_value={"source": "fixture"}))
            stack.enter_context(
                patch("sixcat.run.probe_policy", return_value={"status": "ok", "reason": "fixture"})
            )
            for category in CATEGORIES:
                stack.enter_context(
                    patch(f"sixcat.run.run_{category}", return_value=rows.get(category, default))
                )
            result = run_battery(client, limit=1, skip_code_exec=False)

        self.assertEqual(result["speed"]["total_ctok"], 400)
        self.assertEqual(result["speed"]["total_wall_s"], 5.0)
        self.assertEqual(result["speed"]["suite_tps"], 80.0)
        self.assertEqual(result["speed"]["tps_mean"], 75.0)
        self.assertEqual(result["stats"]["knowledge"]["suite_tps"], 50.0)
        self.assertEqual(result["stats"]["math"]["suite_tps"], 100.0)
        table = __import__("sixcat.run", fromlist=["render_table"]).render_table(result)
        self.assertIn("suite_tps", table)
        self.assertIn("80.0", table)
