from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sixcat.journal import RunJournal, Session, TimeBudget
from sixcat.policy import strict_policy
from sixcat.run import continuation_offer, expected_scored_items, run_math


class SeqClient:
    def __init__(self, answers: list[str]):
        self.policy = strict_policy()
        self.answers = list(answers)
        self.calls = 0

    def complete(self, prompt, **kwargs):
        if self.calls >= len(self.answers):
            raise AssertionError("unexpected extra model call")
        text = self.answers[self.calls]
        self.calls += 1
        return {
            "text": text,
            "finish": "stop",
            "usage": {"completion_tokens": 2, "prompt_tokens": 8},
            "reasoning_content": "",
        }


class TestRetryMerge(unittest.TestCase):
    def test_expected_scope_counts(self):
        self.assertEqual(expected_scored_items(20), 120)
        self.assertEqual(expected_scored_items(20, skip_code_exec=True), 100)
        self.assertEqual(expected_scored_items(None), 884)
        self.assertEqual(expected_scored_items(None, skip_code_exec=True), 720)

    def test_retry_failed_rescores_and_keeps_passes(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "run.jsonl"
            with RunJournal(log, resume=False) as journal:
                journal.append(
                    {"cat": "math", "key": "gsm:18", "ok": False, "pred": "0", "gold": "1", "parse_confidence": "high"}
                )
                journal.append(
                    {"cat": "math", "key": "gsm:9", "ok": True, "pred": "2", "gold": "2", "parse_confidence": "high"}
                )
                session = Session(
                    journal,
                    TimeBudget(None),
                    retry_failed=True,
                    include_remaining=True,
                    retry_mode="failed",
                )
                client = SeqClient(["#### 1"])
                rows = run_math(client, limit=2, session=session)

            self.assertEqual(client.calls, 1)
            by_key = {row["key"]: row for row in rows}
            self.assertEqual(by_key["gsm:18"]["raw_text"], "#### 1")
            self.assertTrue(by_key["gsm:9"]["ok"])
            self.assertEqual(session.continuation_receipt()["failed_rescored"], 1)
            loaded = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            scored = [row for row in loaded if "key" in row]
            self.assertGreaterEqual(len(scored), 3)

    def test_retry_failed_only_does_not_start_remaining_items(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "run.jsonl"
            with RunJournal(log, resume=False) as journal:
                journal.append(
                    {"cat": "math", "key": "gsm:18", "ok": False, "pred": "0", "gold": "1", "parse_confidence": "high"}
                )
                session = Session(
                    journal,
                    TimeBudget(None),
                    retry_failed=True,
                    include_remaining=False,
                    retry_mode="failed",
                )
                client = SeqClient(["#### 1"])
                rows = run_math(client, limit=2, session=session)

            self.assertEqual(client.calls, 1)
            self.assertEqual([row["key"] for row in rows], ["gsm:18"])
            self.assertEqual(rows[0]["raw_text"], "#### 1")

    def test_timeup_during_failed_retry_keeps_previous_fail(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "run.jsonl"
            with RunJournal(log, resume=False) as journal:
                journal.append(
                    {"cat": "math", "key": "gsm:18", "ok": False, "pred": "0", "gold": "1", "parse_confidence": "high"}
                )
                session = Session(
                    journal,
                    TimeBudget(0),
                    retry_failed=True,
                    include_remaining=False,
                    retry_mode="failed",
                )
                client = SeqClient(["#### 1"])
                rows = run_math(client, limit=2, session=session)

            self.assertEqual(client.calls, 0)
            self.assertTrue(session.stopped)
            self.assertEqual(rows[0]["pred"], "0")
            self.assertFalse(rows[0]["ok"])
            self.assertEqual(session.continuation_receipt()["failed_kept_previous"], 1)

    def test_remaining_resume_does_not_rescore_failures(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "run.jsonl"
            with RunJournal(log, resume=False) as journal:
                journal.append(
                    {"cat": "math", "key": "gsm:18", "ok": False, "pred": "0", "gold": "1", "parse_confidence": "high"}
                )
                session = Session(journal, TimeBudget(None), retry_mode="remaining")
                client = SeqClient(["#### 99"])
                rows = run_math(client, limit=2, session=session)

            self.assertEqual(client.calls, 1)
            by_key = {row["key"]: row for row in rows}
            self.assertFalse(by_key["gsm:18"]["ok"])
            self.assertIn("gsm:9", by_key)

    def test_continuation_offer_counts_remaining_and_failed(self):
        offer = continuation_offer(
            {
                "limit": 20,
                "code_execution": "host-guarded",
                "timed_out": True,
                "n": {"knowledge": 20, "math": 8, "truth": 0, "instruct": 0, "code": 0, "tools": 0},
                "items": {
                    "knowledge": [{"cat": "knowledge", "key": "mmlu:18", "ok": False}],
                    "math": [{"cat": "math", "key": "gsm:18", "ok": True}],
                },
            }
        )
        self.assertEqual(offer["expected"], 120)
        self.assertEqual(offer["scored"], 28)
        self.assertEqual(offer["remaining"], 92)
        self.assertEqual(offer["failed"], 1)
        self.assertTrue(offer["can_continue_remaining"])
        self.assertTrue(offer["can_retry_failed"])

    def test_cli_rejects_retry_with_no_resume(self):
        from sixcat.__main__ import main

        with self.assertRaises(SystemExit) as caught:
            main(["--model", "x", "--retry", "failed", "--no-resume", "--log", "missing.jsonl"])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_rejects_retry_without_existing_journal(self):
        from sixcat.__main__ import main

        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "gone.jsonl"
            with self.assertRaises(SystemExit) as caught:
                main(["--model", "x", "--retry", "failed", "--log", str(missing)])
            self.assertEqual(caught.exception.code, 2)

    def test_status_last_write_wins_after_retry(self):
        from tests.test_hermes_skill import _load_script

        status = _load_script("status.py")
        with tempfile.TemporaryDirectory() as td:
            journal = Path(td) / "run.jsonl"
            journal.write_text(
                json.dumps({"cat": "math", "key": "gsm:18", "ok": False, "ts": 1})
                + "\n"
                + json.dumps({"_sixcat_retry": {"mode": "failed", "keys": ["math/gsm:18"]}})
                + "\n"
                + json.dumps({"cat": "math", "key": "gsm:18", "ok": True, "ts": 2})
                + "\n",
                encoding="utf-8",
            )
            summary = status.summarize_journal(journal)
        self.assertEqual(summary["rows"], 1)
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 0)


if __name__ == "__main__":
    unittest.main()
