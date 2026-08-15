import json
import tempfile
import time
import unittest
from pathlib import Path

from sixcat.journal import RunJournal, TimeBudget


class TestJournal(unittest.TestCase):
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
