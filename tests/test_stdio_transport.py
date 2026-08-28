from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from sixcat.client import ChatClient
from sixcat.journal import RunJournal
from sixcat.policy import custom_policy


def _policy():
    return custom_policy(temperature=0.0, thinking=False)


class TestStdioTransport(unittest.TestCase):
    def test_complete_roundtrip_over_stdio(self):
        req_r_fd, req_w_fd = os.pipe()
        ans_r_fd, ans_w_fd = os.pipe()
        req_r = os.fdopen(req_r_fd, "r", encoding="utf-8")
        req_w = os.fdopen(req_w_fd, "w", encoding="utf-8")
        ans_r = os.fdopen(ans_r_fd, "r", encoding="utf-8")
        ans_w = os.fdopen(ans_w_fd, "w", encoding="utf-8")
        client = ChatClient(
            "stdio://harness",
            "glm-5.3-flash",
            _policy(),
            transport="stdio",
            stdio_in=ans_r,
            stdio_out=req_w,
        )
        errors: list[BaseException] = []

        def harness() -> None:
            try:
                req = json.loads(req_r.readline())
                assert req["op"] == "complete"
                assert req["prompt"] == "Say A"
                ans_w.write(
                    json.dumps(
                        {
                            "id": req["id"],
                            "text": "A",
                            "finish": "stop",
                            "usage": {"completion_tokens": 1, "prompt_tokens": 4},
                        }
                    )
                    + "\n"
                )
                ans_w.flush()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=harness)
        thread.start()
        try:
            out = client.complete("Say A", max_tokens=8)
        finally:
            thread.join(timeout=5)
            for fh in (req_r, req_w, ans_r, ans_w):
                try:
                    fh.close()
                except OSError:
                    pass
        self.assertEqual(errors, [])
        self.assertEqual(out["text"], "A")
        self.assertEqual(out["finish"], "stop")
        self.assertEqual(out["usage"]["completion_tokens"], 1)

    def test_openai_journal_without_transport_still_resumes(self):
        identity = {
            "result_schema": "sixcat-v2",
            "parser": "v4",
            "model": "m",
            "base_url": "http://127.0.0.1:8891/v1",
            "policy": "vendor",
            "policy_fingerprint": "abc123def456",
            "budgets": {"knowledge": 8192},
            "limit": 20,
            "request_timeout_seconds": 1800.0,
            "code_execution": "host-guarded",
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.jsonl"
            with RunJournal(path, resume=False, identity=identity) as journal:
                journal.append({"cat": "math", "key": "gsm:0", "ok": True})
            incoming = dict(identity)
            incoming["transport"] = "openai"
            with RunJournal(path, resume=True, identity=incoming) as resumed:
                self.assertEqual(resumed.done_keys(), {("math", "gsm:0")})

    def test_stdio_does_not_resume_openai_journal(self):
        identity = {
            "result_schema": "sixcat-v2",
            "parser": "v4",
            "model": "m",
            "base_url": "http://127.0.0.1:8891/v1",
            "policy": "vendor",
            "policy_fingerprint": "abc123def456",
            "budgets": {"knowledge": 8192},
            "limit": 20,
            "request_timeout_seconds": 1800.0,
            "code_execution": "host-guarded",
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.jsonl"
            with RunJournal(path, resume=False, identity=identity):
                pass
            incoming = dict(identity)
            incoming["transport"] = "stdio"
            incoming["base_url"] = "stdio://harness"
            with self.assertRaises(ValueError) as ctx:
                RunJournal(path, resume=True, identity=incoming)
            self.assertTrue("transport" in str(ctx.exception) or "base_url" in str(ctx.exception))
