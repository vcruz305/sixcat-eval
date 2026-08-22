from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestResultRowSerialization(unittest.TestCase):
    def test_write_result_round_trips_live_shaped_row_without_losing_provenance(self):
        from sixcat.__main__ import _write_result
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
            extra={"seed": 7, "presence_penalty": 0.0},
            source="fixture",
        )
        response_body = {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "I will inspect the complete record before calling the tool.",
                        "reasoning_content": "The requested operation maps to read_file.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 19, "completion_tokens": 31},
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(response_body).encode("utf-8")

        secret_sentinel = "SUPER" + "-SECRET"
        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            out = ChatClient(
                "http://fixture/v1",
                "fixture-model",
                policy,
                api_key=secret_sentinel,
            ).complete("Read README.md", max_tokens=321, tools=[{"type": "function"}])

        row = {
            "cat": "tools",
            "key": "tool:read readme",
            "id": "tool:read readme",
            "ok": True,
            "pred": "read_file",
            "gold": "read_file",
            "finish": out["finish"],
            "ctok": out["usage"]["completion_tokens"],
            "ptok": out["usage"]["prompt_tokens"],
            "request_params": out["request_params"],
            "parse_confidence": "not_applicable",
            "raw_text": out["text"],
            "reasoning_content": out["reasoning_content"],
            "tool_calls": out["tool_calls"],
            "grader": {"name": "structured-tool-call", "item": "read readme"},
        }
        result = {"model": "fixture-model", "items": {"tools": [row]}}

        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "result.json"
            log_path = Path(td) / "result.jsonl"
            with contextlib.redirect_stdout(io.StringIO()):
                _write_result(result, output_path, log_path)
            saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(saved["items"]["tools"][0], row)
        self.assertEqual(saved["items"]["tools"][0]["request_params"], out["request_params"])
        self.assertNotIn("api_key", saved["items"]["tools"][0]["request_params"])
        self.assertNotIn(secret_sentinel, json.dumps(saved))


class TestParserRowReceipts(unittest.TestCase):
    def test_mc_row_preserves_complete_visible_response_and_separate_reasoning(self):
        from sixcat.run import run_truth

        visible = "analysis " * 650 + "\nFinal answer: B"
        reasoning = "private chain supplied by a reasoning_content architecture"

        class FakeClient:
            def complete(self, prompt, **kwargs):
                return {
                    "text": visible,
                    "reasoning_content": reasoning,
                    "finish": "stop",
                    "usage": {"prompt_tokens": 11, "completion_tokens": 777},
                    "request_params": {"temperature": 0.0, "max_tokens": kwargs["max_tokens"]},
                }

        item = {"question": "Which option?", "choices": ["wrong", "right"], "answer": 1}
        with patch("sixcat.run.read_jsonl", return_value=[item]):
            row = run_truth(FakeClient(), limit=1)[0]

        self.assertTrue(row["ok"])
        self.assertEqual(row["raw_text"], visible)
        self.assertGreater(len(row["raw_text"]), 4000)
        self.assertEqual(row["reasoning_content"], reasoning)
        self.assertEqual(row["parse_confidence"], "high")

    def test_gsm_row_preserves_complete_visible_response_and_separate_reasoning(self):
        from sixcat.run import run_math

        visible = "calculation " * 500 + "\n#### 29"
        reasoning = "dedicated calculation trace"

        class FakeClient:
            def complete(self, prompt, **kwargs):
                return {
                    "text": visible,
                    "reasoning_content": reasoning,
                    "finish": "stop",
                    "usage": {"prompt_tokens": 17, "completion_tokens": 602},
                    "request_params": {"temperature": 0.0, "max_tokens": kwargs["max_tokens"]},
                }

        item = {"question": "What is the total?", "answer": "work\n#### 29"}
        with patch("sixcat.run.read_jsonl", return_value=[item]):
            row = run_math(FakeClient(), limit=1)[0]

        self.assertTrue(row["ok"])
        self.assertEqual(row["raw_text"], visible)
        self.assertGreater(len(row["raw_text"]), 4000)
        self.assertEqual(row["reasoning_content"], reasoning)
        self.assertEqual(row["parse_confidence"], "high")


class TestCodeRowReceipts(unittest.TestCase):
    def test_humaneval_row_keeps_full_completion_and_deterministic_dataset_locator(self):
        from sixcat.code import run_code

        prompt = 'def add(a, b):\n    """Return the sum."""\n'
        completion = "    # deliberately long visible completion receipt\n" * 8 + "    return a + b\n"
        reasoning = "Use Python addition and retain the exact generated code separately."
        item = {
            "task_id": "HumanEval/fixture-add",
            "prompt": prompt,
            "test": "def check(candidate):\n    assert candidate(2, 3) == 5\n",
            "entry_point": "add",
        }

        class FakeClient:
            def complete(self, request_prompt, **kwargs):
                return {
                    "text": completion,
                    "reasoning_content": reasoning,
                    "finish": "stop",
                    "usage": {"prompt_tokens": 23, "completion_tokens": 88},
                    "request_params": {"temperature": 0.0, "max_tokens": kwargs["max_tokens"]},
                }

        with patch("sixcat.code.read_jsonl", return_value=[item]):
            row = run_code(FakeClient(), limit=1, skip_code_exec=False)[0]

        self.assertTrue(row["ok"])
        self.assertEqual(row["raw_text"], completion)
        self.assertGreater(len(row["raw_text"]), len(row["pred"]))
        self.assertEqual(row["reasoning_content"], reasoning)
        self.assertEqual(row["parse_confidence"], "not_applicable")
        self.assertEqual(row["task_id"], item["task_id"])
        self.assertEqual(row["entry_point"], "add")
        self.assertEqual(
            row["grader"],
            {
                "name": "humaneval-local",
                "dataset": "humaneval.jsonl",
                "task_id": item["task_id"],
                "entry_point": "add",
            },
        )


class TestConfidenceAccounting(unittest.TestCase):
    def test_category_stats_partitions_every_row_into_an_explicit_confidence_bucket(self):
        from sixcat.score import category_stats

        stats = category_stats(
            [
                {"ok": True, "parse_confidence": "high"},
                {"ok": False, "parse_confidence": "low"},
                {"ok": True, "parse_confidence": "not_applicable"},
                {"ok": True},
                {"ok": False, "parse_confidence": "unexpected"},
            ]
        )

        self.assertEqual(stats["n"], 5)
        self.assertEqual(stats["parse_high_confidence"], 1)
        self.assertEqual(stats["parse_low_confidence"], 1)
        self.assertEqual(stats["parse_confidence_not_applicable"], 1)
        self.assertEqual(stats["parse_confidence_missing"], 2)
        self.assertEqual(
            stats["parse_high_confidence"]
            + stats["parse_low_confidence"]
            + stats["parse_confidence_not_applicable"]
            + stats["parse_confidence_missing"],
            stats["n"],
        )

    def test_low_confidence_threshold_uses_only_applicable_parser_rows(self):
        from sixcat.run import CATEGORIES, build_overall_flags

        stats = {
            category: {
                "n": 10,
                "truncated": 0,
                "parse_high_confidence": 0,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 10,
                "parse_confidence_missing": 0,
            }
            for category in CATEGORIES
        }
        stats["math"].update(
            parse_high_confidence=3,
            parse_low_confidence=2,
            parse_confidence_not_applicable=5,
        )

        self.assertEqual(build_overall_flags(stats), ["low-confidence-parses:math"])

    def test_missing_confidence_is_an_explicit_overall_flag(self):
        from sixcat.run import CATEGORIES, build_overall_flags

        stats = {
            category: {
                "n": 10,
                "truncated": 0,
                "parse_high_confidence": 0,
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": 10,
                "parse_confidence_missing": 0,
            }
            for category in CATEGORIES
        }
        stats["instruct"].update(
            parse_confidence_not_applicable=9,
            parse_confidence_missing=1,
        )

        self.assertEqual(build_overall_flags(stats), ["missing-parse-confidence:instruct"])

    def test_run_table_exposes_all_confidence_buckets_and_missing_warning(self):
        from sixcat.run import CATEGORIES, build_overall_flags, render_table

        stats = {
            category: {
                "n": 1,
                "truncated": 0,
                "parse_high_confidence": int(category in {"knowledge", "math", "truth"}),
                "parse_low_confidence": 0,
                "parse_confidence_not_applicable": int(category in {"instruct", "code", "tools"}),
                "parse_confidence_missing": 0,
            }
            for category in CATEGORIES
        }
        stats["instruct"].update(parse_confidence_not_applicable=0, parse_confidence_missing=1)
        flags = build_overall_flags(stats)
        result = {
            "model": "fixture",
            "base_url": "fixture://",
            "policy": {"name": "strict"},
            "policy_source": "fixture",
            "policy_fingerprint": "fixture-fp",
            "categories": {category: 100.0 for category in CATEGORIES},
            "stats": stats,
            "n": {category: 1 for category in CATEGORIES},
            "overall": {"policy": "strict", "score": 100.0},
            "overall_flags": flags,
            "timed_out": False,
        }

        table = render_table(result)

        header = next(line for line in table.splitlines() if line.startswith("category"))
        self.assertIn("high", header)
        self.assertIn("n/a", header)
        self.assertIn("miss", header)
        self.assertIn("missing-parse-confidence:instruct", table)
        self.assertIn("WARNING: missing parse confidence", table)


if __name__ == "__main__":
    unittest.main()
