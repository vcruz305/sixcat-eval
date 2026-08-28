from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from sixcat.journal import RunJournal, Session, TimeBudget
from sixcat.run import run_truth


class OverlapClient:
    def __init__(self):
        self._lock = threading.Lock()
        self.inflight = 0
        self.max_inflight = 0

    def complete(self, prompt, **kwargs):
        with self._lock:
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
        time.sleep(0.2)
        with self._lock:
            self.inflight -= 1
        return {
            "text": "A",
            "finish": "stop",
            "usage": {"completion_tokens": 1, "prompt_tokens": 8},
            "request_params": kwargs,
        }


class TestConcurrentJournal(unittest.TestCase):
    def test_parallel_appends_are_valid_jsonl_and_all_keys_reload(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.jsonl"
            journal = RunJournal(path, resume=False)
            errors: list[BaseException] = []

            def worker(i: int) -> None:
                try:
                    journal.append({"cat": "truth", "key": f"tqa:{i}", "ok": True, "pred": "A"})
                except BaseException as exc:  # noqa: BLE001 — collect for the parent thread
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            journal.close()
            self.assertEqual(errors, [])
            lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            parsed = [json.loads(ln) for ln in lines]
            keys = {row["key"] for row in parsed if "key" in row}
            self.assertEqual(keys, {f"tqa:{i}" for i in range(8)})
            with RunJournal(path, resume=True) as resumed:
                self.assertEqual(len(resumed.done_keys()), 8)


class TestConcurrentCategory(unittest.TestCase):
    def test_run_truth_concurrency_overlaps_complete_calls(self):
        items = [
            {"question": f"q{i}", "choices": ["yes", "no"], "answer": 0}
            for i in range(4)
        ]
        client = OverlapClient()
        with tempfile.TemporaryDirectory() as td:
            journal = RunJournal(Path(td) / "run.jsonl", resume=False)
            session = Session(journal, TimeBudget(None), concurrency=4)
            try:
                with patch("sixcat.run.read_jsonl", return_value=items):
                    rows = run_truth(client, limit=4, session=session)
            finally:
                journal.close()
        self.assertEqual(len(rows), 4)
        self.assertGreaterEqual(
            client.max_inflight,
            2,
            f"expected overlapping HTTP, max_inflight={client.max_inflight}",
        )

    def test_concurrency_1_stays_serial(self):
        items = [
            {"question": f"q{i}", "choices": ["yes", "no"], "answer": 0}
            for i in range(3)
        ]
        client = OverlapClient()
        with patch("sixcat.run.read_jsonl", return_value=items):
            rows = run_truth(client, limit=3, session=None)
        self.assertEqual(len(rows), 3)
        self.assertEqual(client.max_inflight, 1)


class TestConcurrencyCli(unittest.TestCase):
    def test_help_lists_concurrency(self):
        proc = subprocess.run(
            [sys.executable, "-m", "sixcat", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--concurrency", proc.stdout)
