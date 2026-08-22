"""Phase 2 (sixcat v2.1, B4): style-case suite for the position-aware parsers.

These are the cases quoted verbatim in sixcat-v2-neutrality-plan-2026-08-20.md section 1
(B4) and sixcat-sampling-policy-review-2026-08-20.md. The original probe script referenced
by those docs (logs/probe_parser_bias.py) could not be located on disk when this suite was
written (searched V:\\ornith-lowbit-tests and the repo; only ab_sampling.txt / math_jump.txt
survived) -- this file reconstructs the documented cases rather than claiming to recover the
original. If the original script turns up, diff it against this file and merge any case it
covers that this one doesn't.
"""

import unittest
from unittest.mock import patch

from sixcat.score import extract_gsm_number, extract_gsm_number_conf, extract_mc_letter, extract_mc_letter_conf


class TestMcLetterStyles(unittest.TestCase):
    # -- from the v1 review doc / v2 plan, gold B unless noted --
    def test_bare_letter(self):
        self.assertEqual(extract_mc_letter("B"), "B")

    def test_answer_is_cue(self):
        self.assertEqual(extract_mc_letter("The answer is B"), "B")

    def test_answer_cue_with_other_letters_mentioned(self):
        self.assertEqual(extract_mc_letter("A is wrong. The answer is B, not C"), "B")

    def test_enumerate_then_conclude_was_v1_miss(self):
        # v1: last-letter-wins picked D. Correct reasoning says B (the only "yes").
        text = "Let me check each. A? no. B? yes. C? no. D? no."
        self.assertEqual(extract_mc_letter(text), "B")

    # -- confidence contract --
    def test_high_confidence_on_explicit_cue(self):
        letter, conf = extract_mc_letter_conf("The answer is B")
        self.assertEqual(letter, "B")
        self.assertEqual(conf, "high")

    def test_low_confidence_on_bare_fallback(self):
        # no cue, no marker, no lone line, no affirm word -- must fall through to "low"
        letter, conf = extract_mc_letter_conf("I would pick B over the others honestly")
        self.assertEqual(letter, "B")
        self.assertEqual(conf, "low")

    # -- format markers --
    def test_boxed(self):
        self.assertEqual(extract_mc_letter(r"reasoning... \boxed{C}"), "C")

    def test_bold(self):
        self.assertEqual(extract_mc_letter("My pick: **D**"), "D")

    def test_hash_marker(self):
        self.assertEqual(extract_mc_letter("blah blah\n#### A"), "A")

    def test_lone_line(self):
        self.assertEqual(extract_mc_letter("Thinking about it...\nB\n"), "B")

    # -- reasoning-trace stripping --
    def test_think_block_never_supplies_the_answer(self):
        text = "<think>maybe A, or D, hard to say</think>The answer is C"
        self.assertEqual(extract_mc_letter(text), "C")

    def test_no_letters_returns_none(self):
        self.assertIsNone(extract_mc_letter("I'm not sure."))

    def test_empty_string_returns_none(self):
        self.assertIsNone(extract_mc_letter(""))

    # -- original three-case suite from tests/test_score.py, reproduced for regression --
    def test_original_suite_still_passes(self):
        self.assertEqual(extract_mc_letter("The answer is B."), "B")
        self.assertEqual(extract_mc_letter("D"), "D")
        self.assertEqual(extract_mc_letter("I think (C) is correct"), "C")


class TestGsmNumberStyles(unittest.TestCase):
    def test_hash_number(self):
        self.assertEqual(extract_gsm_number("... #### 29"), "29")

    def test_reasoning_then_conclude_confirmed_at_end(self):
        # already correct even under v1 (the confirming number happens to be last) --
        # kept here as a regression guard, not a fix.
        text = "Total 29. Verify: 15+3+11 = 29. Confirmed 29"
        self.assertEqual(extract_gsm_number(text), "29")

    def test_answer_cue_before_trailing_arithmetic_was_v1_miss(self):
        # v1: last-number-wins picked 11 (from "15 + 3 + 11"). Correct answer is 29,
        # explicitly stated first via an "Answer is" cue.
        text = "Answer is 29. Check: 15 + 3 + 11"
        self.assertEqual(extract_gsm_number(text), "29")

    def test_boxed_number(self):
        self.assertEqual(extract_gsm_number(r"work shown... \boxed{42}"), "42")

    def test_comma_thousands(self):
        self.assertEqual(extract_gsm_number("The total is 1,240 dollars."), "1240")

    def test_high_confidence_on_hash(self):
        n, conf = extract_gsm_number_conf("#### 7")
        self.assertEqual((n, conf), ("7", "high"))

    def test_low_confidence_on_bare_fallback(self):
        n, conf = extract_gsm_number_conf("I counted roughly 12 of them I think")
        self.assertEqual((n, conf), ("12", "low"))

    def test_think_block_never_supplies_the_answer(self):
        text = "<think>maybe 11, or 15</think>Answer is 29"
        self.assertEqual(extract_gsm_number(text), "29")

    def test_no_numbers_returns_none(self):
        self.assertIsNone(extract_gsm_number("no numbers here"))

    def test_trailing_double_zero_decimal_normalizes(self):
        # found via Phase 2 adjudication on a live run: "29.00" must equal gold "29",
        # not just the single-zero "29.0" case the old normalizer handled.
        self.assertEqual(extract_gsm_number("Answer is 29.00"), "29")
        self.assertEqual(extract_gsm_number("#### 4.50"), "4.5")
        self.assertEqual(extract_gsm_number("#### 0.00"), "0")


class TestInstructResponseStyles(unittest.TestCase):
    def test_dedicated_reasoning_does_not_change_score_and_full_receipt_is_retained(self):
        from sixcat.run import run_instruct

        visible = "quiet lowercase prose without forbidden punctuation " * 8
        reasoning = "I considered a Draft, with punctuation and Capitals."
        item = {
            "key": "style-1",
            "prompt": "reply in lowercase without a comma",
            "instruction_id_list": ["punctuation:no_comma", "change_case:english_lowercase"],
            "kwargs": [{}, {}],
        }

        class FakeClient:
            def complete(self, prompt, **kwargs):
                return {
                    "text": visible,
                    "reasoning_content": reasoning,
                    "finish": "stop",
                    "usage": {"prompt_tokens": 9, "completion_tokens": 51},
                    "request_params": {"temperature": 0.0, "max_tokens": kwargs["max_tokens"]},
                }

        with patch("sixcat.run.read_jsonl", return_value=[item]):
            row = run_instruct(FakeClient(), limit=1)[0]

        self.assertTrue(row["ok"])
        self.assertEqual(row["raw_text"], visible)
        self.assertGreater(len(row["raw_text"]), len(row["pred"]))
        self.assertEqual(row["reasoning_content"], reasoning)
        self.assertEqual(row["parse_confidence"], "not_applicable")
        self.assertEqual(row["instruction_id_list"], item["instruction_id_list"])
        self.assertEqual(row["kwargs"], item["kwargs"])
        self.assertEqual(row["prompt"], item["prompt"])
        self.assertEqual(row["grader"], {"name": "ifeval-local", "item_key": "style-1"})


class TestStructuredToolResponseStyles(unittest.TestCase):
    def test_correct_tool_name_with_wrong_arguments_fails(self):
        from sixcat.tools import run_tools

        class FakeClient:
            def complete(self, prompt, **kwargs):
                return {
                    "text": "",
                    "reasoning_content": "",
                    "tool_calls": [{
                        "id": "call_1", "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"wrong.txt"}'},
                    }],
                    "finish": "tool_calls",
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    "request_params": kwargs,
                }

        item = ("exact path", [("read_file", {"path": "README.md"})], "Read README.md exactly.")
        with patch("sixcat.tools.ITEMS", [item]):
            row = run_tools(FakeClient(), limit=1)[0]

        self.assertFalse(row["ok"])

    def test_exact_multi_call_sequence_and_arguments_pass(self):
        from sixcat.tools import run_tools

        class FakeClient:
            def complete(self, prompt, **kwargs):
                calls = [
                    {"function": {"name": "add", "arguments": '{"a":19,"b":23}'}},
                    {"function": {"name": "add", "arguments": {"a": 100, "b": 1}}},
                ]
                return {
                    "text": "", "reasoning_content": "", "tool_calls": calls,
                    "finish": "tool_calls", "usage": {}, "request_params": kwargs,
                }

        item = (
            "two adds",
            [("add", {"a": 19, "b": 23}), ("add", {"a": 100, "b": 1})],
            "Call add twice in order.",
        )
        with patch("sixcat.tools.ITEMS", [item]):
            row = run_tools(FakeClient(), limit=1)[0]

        self.assertTrue(row["ok"])

    def test_preceding_reasoning_cannot_override_structured_call_and_full_receipt_is_retained(self):
        from sixcat.tools import run_tools

        visible = "I first considered list_dir but the request requires reading the complete file. " * 3
        reasoning = "Architecture-specific reasoning channel: select read_file after comparison."
        tool_calls = [
            {
                "id": "call_style",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
            }
        ]

        class FakeClient:
            def complete(self, prompt, **kwargs):
                return {
                    "text": visible,
                    "reasoning_content": reasoning,
                    "tool_calls": tool_calls,
                    "finish": "tool_calls",
                    "usage": {"prompt_tokens": 21, "completion_tokens": 33},
                    "request_params": {"temperature": 0.0, "max_tokens": kwargs["max_tokens"]},
                }

        item = ("style read", "read_file", "Read README.md with the correct tool.")
        with patch("sixcat.tools.ITEMS", [item]):
            row = run_tools(FakeClient(), limit=1)[0]

        self.assertTrue(row["ok"])
        self.assertEqual(row["pred"], "read_file")
        self.assertEqual(row["gold"], "read_file")
        self.assertEqual(row["raw_text"], visible)
        self.assertGreater(len(row["raw_text"]), 80)
        self.assertEqual(row["reasoning_content"], reasoning)
        self.assertEqual(row["tool_calls"], tool_calls)
        self.assertEqual(row["parse_confidence"], "not_applicable")
        self.assertEqual(row["grader"], {"name": "structured-tool-call", "item": "style read"})
        self.assertEqual(row["prompt"], item[2])


if __name__ == "__main__":
    unittest.main()
