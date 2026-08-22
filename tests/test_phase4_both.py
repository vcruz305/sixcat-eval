from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TestBothPolicyCli(unittest.TestCase):
    @staticmethod
    def _result(client, *args, **kwargs) -> dict:
        from sixcat.run import CATEGORIES

        policy = client.policy
        return {
            "model": client.model,
            "base_url": client.base_url,
            "policy": policy.to_dict(),
            "policy_source": policy.source,
            "policy_probe": "ok",
            "policy_fingerprint": policy.fingerprint,
            "budgets": dict(policy.budgets),
            "parser": "v3",
            "code_execution": "disabled" if kwargs.get("skip_code_exec") else "host-guarded",
            "limit": 1,
            "timed_out": False,
            "categories": {category: None for category in CATEGORIES},
            "stats": {category: {} for category in CATEGORIES},
            "overall": {"policy": policy.name, "score": None},
            "overall_flags": [],
            "n": {category: 0 for category in CATEGORIES},
            "items": {category: [] for category in CATEGORIES},
        }

    def test_both_runs_strict_then_vendor_with_independent_resources_and_artifacts(self):
        from sixcat.__main__ import main

        clients = []

        def make_client(base_url, model, policy, api_key="none", timeout=180.0):
            client = SimpleNamespace(
                base_url=base_url,
                model=model,
                policy=policy,
                api_key=api_key,
            )
            clients.append(client)
            return client

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            requested_out = root / "phase4_both.json"
            requested_log = root / "phase4_both.jsonl"
            strict_out = root / "phase4_both.strict.json"
            vendor_out = root / "phase4_both.vendor.json"
            strict_log = root / "phase4_both.strict.jsonl"
            vendor_log = root / "phase4_both.vendor.jsonl"
            stdout = io.StringIO()
            with (
                patch("sixcat.__main__.RunJournal") as journal_type,
                patch("sixcat.__main__.Session") as session_type,
                patch("sixcat.__main__.TimeBudget") as budget_type,
                patch("sixcat.__main__.ChatClient", side_effect=make_client),
                patch("sixcat.__main__.run_battery", side_effect=self._result) as run_battery,
                patch("sixcat.__main__.render_table", side_effect=lambda result: f"table-{result['policy']['name']}"),
                contextlib.redirect_stdout(stdout),
            ):
                rc = main(
                    [
                        "--model",
                        "ornith-nomtp",
                        "--policy",
                        "both",
                        "--limit",
                        "1",
                        "--max-minutes",
                        "15",
                        "--seed",
                        "1",
                        "--budget",
                        "math=2222",
                        "--out",
                        str(requested_out),
                        "--log",
                        str(requested_log),
                        "--no-resume",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertEqual([client.policy.name for client in clients], ["strict", "vendor"])
            self.assertEqual([client.policy.budgets["math"] for client in clients], [2222, 2222])
            self.assertEqual(clients[1].policy.extra["seed"], 1)
            self.assertEqual(run_battery.call_count, 2)
            self.assertEqual(budget_type.call_count, 2)
            self.assertEqual(
                [call.kwargs for call in budget_type.call_args_list],
                [{"seconds": 900.0}, {"seconds": 900.0}],
            )
            self.assertEqual(session_type.call_count, 2)
            self.assertEqual(
                [call.args[0] for call in journal_type.call_args_list],
                [strict_log, vendor_log],
            )
            journal_kwargs = [call.kwargs for call in journal_type.call_args_list]
            self.assertEqual([kwargs["resume"] for kwargs in journal_kwargs], [False, False])
            identities = [kwargs["identity"] for kwargs in journal_kwargs]
            self.assertEqual([identity["policy"] for identity in identities], ["strict", "vendor"])
            self.assertEqual([identity["model"] for identity in identities], ["ornith-nomtp", "ornith-nomtp"])
            self.assertEqual([identity["limit"] for identity in identities], [1, 1])
            self.assertEqual([identity["budgets"]["math"] for identity in identities], [2222, 2222])
            self.assertNotEqual(identities[0]["policy_fingerprint"], identities[1]["policy_fingerprint"])
            self.assertEqual(journal_type.return_value.close.call_count, 2)
            self.assertFalse(requested_out.exists())
            self.assertTrue(strict_out.exists())
            self.assertTrue(vendor_out.exists())
            self.assertEqual(json.loads(strict_out.read_text(encoding="utf-8"))["policy"]["name"], "strict")
            self.assertEqual(json.loads(vendor_out.read_text(encoding="utf-8"))["policy"]["name"], "vendor")
            output = stdout.getvalue()
            self.assertLess(output.index("=== STRICT ==="), output.index("=== VENDOR ==="))
            self.assertIn(f"wrote {strict_out}", output)
            self.assertIn(f"wrote {vendor_out}", output)

    def test_both_without_paths_derives_separate_default_results_and_journals(self):
        from sixcat.__main__ import main

        def make_client(base_url, model, policy, api_key="none", timeout=180.0):
            return SimpleNamespace(
                base_url=base_url,
                model=model,
                policy=policy,
                api_key=api_key,
            )

        with tempfile.TemporaryDirectory() as td:
            previous = Path.cwd()
            os.chdir(td)
            try:
                with (
                    patch("sixcat.__main__.ChatClient", side_effect=make_client),
                    patch("sixcat.__main__.run_battery", side_effect=self._result),
                    patch("sixcat.__main__.render_table", return_value="ok"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    rc = main(["--model", "ornith-nomtp", "--policy", "both", "--limit", "1", "--no-resume"])

                self.assertEqual(rc, 0)
                expected = (
                    Path("results/ornith-nomtp.strict.json"),
                    Path("results/ornith-nomtp.vendor.json"),
                    Path("results/ornith-nomtp.strict.jsonl"),
                    Path("results/ornith-nomtp.vendor.jsonl"),
                )
                for path in expected:
                    with self.subTest(path=path):
                        self.assertTrue(path.exists())
                self.assertEqual(json.loads(expected[0].read_text(encoding="utf-8"))["policy"]["name"], "strict")
                self.assertEqual(json.loads(expected[1].read_text(encoding="utf-8"))["policy"]["name"], "vendor")
            finally:
                os.chdir(previous)

    def test_both_scope_mismatch_returns_nonzero_and_preserves_artifacts(self):
        from sixcat.__main__ import main

        def make_client(base_url, model, policy, api_key="none", timeout=180.0):
            return SimpleNamespace(
                base_url=base_url,
                model=model,
                policy=policy,
                api_key=api_key,
            )

        def mismatched_result(client, *args, **kwargs):
            result = self._result(client, *args, **kwargs)
            result["code_execution"] = "disabled"
            if client.policy.name == "vendor":
                result["n"]["knowledge"] = 1
            return result

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "both.json"
            log = root / "both.jsonl"
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch("sixcat.__main__.RunJournal"),
                patch("sixcat.__main__.Session"),
                patch("sixcat.__main__.TimeBudget"),
                patch("sixcat.__main__.ChatClient", side_effect=make_client),
                patch("sixcat.__main__.run_battery", side_effect=mismatched_result),
                patch("sixcat.__main__.render_table", return_value="ok"),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                rc = main(
                    [
                        "--model",
                        "ornith-nomtp",
                        "--policy",
                        "both",
                        "--limit",
                        "1",
                        "--out",
                        str(out),
                        "--log",
                        str(log),
                        "--no-resume",
                    ]
                )

            self.assertEqual(rc, 2)
            self.assertIn("ERROR: RUN SCOPE MISMATCH", stderr.getvalue())
            self.assertIn("WARNING: RUN SCOPE MISMATCH", stdout.getvalue())
            self.assertIn("NOT COMPARABLE", stdout.getvalue())
            self.assertTrue((root / "both.strict.json").exists())
            self.assertTrue((root / "both.vendor.json").exists())

    def test_vendor_failure_is_raised_and_both_journals_are_closed(self):
        from unittest.mock import MagicMock

        from sixcat.__main__ import main

        clients = []

        def make_client(base_url, model, policy, api_key="none", timeout=180.0):
            client = SimpleNamespace(
                base_url=base_url,
                model=model,
                policy=policy,
                api_key=api_key,
            )
            clients.append(client)
            return client

        def fail_vendor(client, *args, **kwargs):
            if client.policy.name == "vendor":
                raise RuntimeError("policy probe failed: vendor thinking trace missing")
            return self._result(client)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            journals = [MagicMock(), MagicMock()]
            strict_out = root / "run.strict.json"
            vendor_out = root / "run.vendor.json"
            with (
                patch("sixcat.__main__.RunJournal", side_effect=journals),
                patch("sixcat.__main__.ChatClient", side_effect=make_client),
                patch("sixcat.__main__.run_battery", side_effect=fail_vendor),
                patch("sixcat.__main__.render_table", return_value="ok"),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaisesRegex(RuntimeError, "policy probe failed.*vendor"),
            ):
                main(
                    [
                        "--model",
                        "ornith-nomtp",
                        "--policy",
                        "both",
                        "--out",
                        str(root / "run.json"),
                        "--log",
                        str(root / "run.jsonl"),
                        "--no-resume",
                    ]
                )

            self.assertEqual([client.policy.name for client in clients], ["strict", "vendor"])
            journals[0].close.assert_called_once_with()
            journals[1].close.assert_called_once_with()
            self.assertTrue(strict_out.exists())
            self.assertFalse(vendor_out.exists())


if __name__ == "__main__":
    unittest.main()
