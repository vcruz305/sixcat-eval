import json
import tempfile
import time
import unittest
from pathlib import Path

from sixcat.journal import RunJournal, TimeBudget


class TestJournal(unittest.TestCase):
    IDENTITY = {
        "result_schema": "sixcat-v2",
        "parser": "v2",
        "model": "model-a",
        "base_url": "http://127.0.0.1:8083/v1",
        "policy": "vendor",
        "policy_fingerprint": "abc123def456",
        "budgets": {"knowledge": 1597, "math": 2048},
        "limit": 20,
        "request_timeout_seconds": 180.0,
    }

    def test_append_and_reload_skips_done_keys(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "run.jsonl"
            j = RunJournal(p)
            j.append({"cat": "math", "key": "gsm:0", "ok": True, "pred": "29", "gold": "29"})
            j.append({"cat": "math", "key": "gsm:1", "ok": False, "pred": "1", "gold": "2"})
            j.close()
            j2 = RunJournal(p)
            try:
                self.assertEqual(j2.done_keys(), {("math", "gsm:0"), ("math", "gsm:1")})
                rows = j2.rows_for("math")
                self.assertEqual(len(rows), 2)
                self.assertTrue(rows[0]["ok"])
                self.assertFalse(rows[1]["ok"])
            finally:
                j2.close()

    def test_corrupt_last_line_is_ignored_on_reload(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "run.jsonl"
            p.write_text('{"cat":"code","key":"x","ok":true}\n{this is broken', encoding="utf-8")
            j = RunJournal(p)
            try:
                self.assertEqual(j.done_keys(), {("code", "x")})
            finally:
                j.close()

    def test_same_run_identity_resumes_and_header_is_not_a_scored_row(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "run.jsonl"
            with RunJournal(p, resume=False, identity=self.IDENTITY) as journal:
                journal.append({"cat": "truth", "key": "tqa:0", "ok": True})

            records = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0], {"_sixcat_run": self.IDENTITY})
            self.assertEqual(len(records), 2)

            with RunJournal(p, resume=True, identity=self.IDENTITY) as resumed:
                self.assertEqual(resumed.identity, self.IDENTITY)
                self.assertEqual(resumed.done_keys(), {("truth", "tqa:0")})
                self.assertEqual(len(resumed.rows_for("truth")), 1)

    def test_resume_rejects_every_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "run.jsonl"
            with RunJournal(p, resume=False, identity=self.IDENTITY):
                pass

            mismatches = {
                "model": "model-b",
                "base_url": "http://127.0.0.1:8000/v1",
                "policy_fingerprint": "different1234",
                "parser": "v3",
                "budgets": {"knowledge": 1, "math": 2},
                "limit": None,
                "request_timeout_seconds": 900.0,
            }
            for field, value in mismatches.items():
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "run identity mismatch"):
                    RunJournal(p, resume=True, identity={**self.IDENTITY, field: value})

    def test_resume_rejects_legacy_rows_without_identity(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "run.jsonl"
            p.write_text('{"cat":"math","key":"gsm:0","ok":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing run identity"):
                RunJournal(p, resume=True, identity=self.IDENTITY)

    def test_no_resume_replaces_old_identity_and_rows(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "run.jsonl"
            with RunJournal(p, resume=False, identity=self.IDENTITY) as journal:
                journal.append({"cat": "math", "key": "gsm:0", "ok": True})

            replacement = {**self.IDENTITY, "model": "model-b"}
            with RunJournal(p, resume=False, identity=replacement) as journal:
                self.assertEqual(journal.done_keys(), set())

            records = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records, [{"_sixcat_run": replacement}])

    def test_new_run_identity_declares_limit_is_per_category(self):
        from sixcat.__main__ import _journal_identity
        from sixcat.policy import strict_policy

        identity = _journal_identity(
            model="model-a",
            base_url="http://127.0.0.1:8083/v1",
            policy=strict_policy(),
            limit=20,
            request_timeout=180.0,
            skip_code_exec=False,
        )

        self.assertEqual(identity["limit"], 20)
        self.assertEqual(identity["limit_scope"], "per_category")


class TestTimeBudget(unittest.TestCase):
    def test_expired_after_seconds(self):
        b = TimeBudget(seconds=0.05)
        self.assertFalse(b.expired())
        time.sleep(0.07)
        self.assertTrue(b.expired())

    def test_none_never_expires(self):
        self.assertFalse(TimeBudget(seconds=None).expired())


if __name__ == "__main__":
    unittest.main()
