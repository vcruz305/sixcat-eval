from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from sixcat.score import CATEGORIES


def _legacy_v1_document() -> dict:
    return {
        "model": "legacy-model",
        "base_url": "http://legacy/v1",
        "categories": {category: float(index * 10) for index, category in enumerate(CATEGORIES, start=1)},
        "overall": 35.0,
        "n": {category: 1 for category in CATEGORIES},
    }


def _current_document(*, name: str = "strict", fingerprint: str = "aaaaaaaaaaaa") -> dict:
    return {
        "model": "current-model",
        "base_url": "http://current/v1",
        "policy": {"name": name, "temperature": 0.0, "budgets": {category: 1 for category in CATEGORIES}},
        "policy_source": "fixture-source",
        "policy_probe": "ok",
        "policy_fingerprint": fingerprint,
        "budgets": {category: 1 for category in CATEGORIES},
        "parser": "v3",
        "code_execution": "disabled",
        "categories": {category: 50.0 for category in CATEGORIES},
        "stats": {
            category: {"n": 1, "truncated": 0, "parse_low_confidence": 0}
            for category in CATEGORIES
        },
        "overall": {"policy": name, "score": 50.0},
        "overall_label": f"overall[{name}]",
        "overall_flags": [],
        "n": {category: 1 for category in CATEGORIES},
    }


class TestResultLoading(unittest.TestCase):
    def test_legacy_v1_is_normalized_in_memory_with_warning_and_distinct_labels(self):
        from sixcat.report import load_result

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy.json"
            path.write_text(json.dumps(_legacy_v1_document(), indent=2), encoding="utf-8")
            before = path.read_bytes()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                first = load_result(path)
                second = load_result(path)
            after = path.read_bytes()

        warning_text = stderr.getvalue()
        self.assertEqual(warning_text.count("WARNING: LEGACY V1 RESULT"), 2)
        self.assertIn("policy=strict", warning_text)
        self.assertIn("parser=v1", warning_text)
        self.assertIn("not comparable to current strict/parser-v3", warning_text)
        self.assertEqual(first["policy"]["name"], "strict")
        self.assertEqual(first["parser"], "v1")
        self.assertEqual(first["policy_source"], "legacy-v1-assumption")
        self.assertEqual(first["policy_probe"], "not-recorded-v1")
        self.assertTrue(first["policy_fingerprint"].startswith("legacy-v1-"))
        self.assertEqual(first["policy_fingerprint"], second["policy_fingerprint"])
        self.assertEqual(first["overall_label"], "overall[strict;parser=v1;legacy-assumed]")
        self.assertEqual(first["overall"], {"policy": "strict", "score": 35.0})
        self.assertEqual(before, after)

    def test_archived_parser_v2_result_remains_readable_but_keeps_its_identity(self):
        from sixcat.report import normalise_result

        document = _current_document()
        document["parser"] = "v2"

        normalised = normalise_result(document, source="archived-v2")

        self.assertEqual(normalised["parser"], "v2")

    def test_current_result_missing_required_policy_metadata_fails_clearly(self):
        from sixcat.report import ResultFormatError, load_result

        document = _current_document()
        del document["policy_fingerprint"]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "broken-current.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ResultFormatError, "missing required policy metadata.*policy_fingerprint"):
                load_result(path)

    def test_current_result_rejects_unknown_explicit_schema_marker(self):
        from sixcat.report import ResultFormatError, normalise_result

        document = _current_document()
        document["result_schema"] = "sixcat-v999"

        with self.assertRaisesRegex(ResultFormatError, "result_schema must be sixcat-v2"):
            normalise_result(document)

    def test_marked_v2_requires_valid_code_execution_mode(self):
        from sixcat.report import ResultFormatError, normalise_result

        for value in (None, "sandboxed", True):
            document = _current_document()
            document["result_schema"] = "sixcat-v2"
            for category_stats in document["stats"].values():
                category_stats.update(
                    parse_high_confidence=1,
                    parse_confidence_not_applicable=0,
                    parse_confidence_missing=0,
                )
            if value is None:
                document.pop("code_execution")
            else:
                document["code_execution"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ResultFormatError, "code_execution"):
                normalise_result(document)

    def test_marked_v2_result_requires_every_confidence_bucket(self):
        from sixcat.report import ResultFormatError, normalise_result

        document = _current_document()
        document["result_schema"] = "sixcat-v2"
        for category_stats in document["stats"].values():
            category_stats.update(
                parse_high_confidence=1,
                parse_confidence_not_applicable=0,
                parse_confidence_missing=0,
            )
        del document["stats"]["knowledge"]["parse_confidence_missing"]

        with self.assertRaisesRegex(ResultFormatError, "stats for knowledge missing parse_confidence_missing"):
            normalise_result(document)

    def test_marked_v2_result_rejects_confidence_buckets_that_do_not_sum_to_n(self):
        from sixcat.report import ResultFormatError, normalise_result

        document = _current_document()
        document["result_schema"] = "sixcat-v2"
        for category_stats in document["stats"].values():
            category_stats.update(
                parse_high_confidence=1,
                parse_confidence_not_applicable=0,
                parse_confidence_missing=0,
            )
        document["stats"]["knowledge"]["parse_high_confidence"] = 0

        with self.assertRaisesRegex(ResultFormatError, "confidence buckets for knowledge must sum to n=1"):
            normalise_result(document)

    def test_pre_marker_current_result_remains_readable_with_old_stats(self):
        from sixcat.report import normalise_result

        document = _current_document()

        normalised = normalise_result(document)

        self.assertNotIn("result_schema", normalised)
        self.assertEqual(normalised["stats"]["knowledge"], document["stats"]["knowledge"])

    def test_parser_v2_without_policy_is_not_misread_as_legacy(self):
        from sixcat.report import ResultFormatError, load_result

        document = _legacy_v1_document()
        document["parser"] = "v2"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "broken-v2.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ResultFormatError, "not an unambiguous legacy v1 result"):
                load_result(path)

    def test_current_only_markers_are_not_misread_as_legacy_or_warned(self):
        from sixcat.report import ResultFormatError, normalise_result

        markers = {
            "result_schema": "sixcat-v2",
            "parser": "v2",
            "policy_source": "fixture-source",
            "policy_probe": "ok",
            "policy_probe_details": {"status": "ok"},
            "policy_fingerprint": "fixture-fingerprint",
            "budgets": {},
            "server_props": {},
            "stats": {},
            "overall_flags": [],
            "overall_label": "overall[strict]",
            "items": {},
            "log": "fixture.jsonl",
        }

        for marker, value in markers.items():
            with self.subTest(marker=marker):
                document = _legacy_v1_document()
                document[marker] = value
                warnings = io.StringIO()

                with self.assertRaisesRegex(ResultFormatError, "not an unambiguous legacy v1 result"):
                    normalise_result(document, source=f"mixed-{marker}", warning_stream=warnings)

                self.assertEqual(warnings.getvalue(), "")

    def test_structured_overall_is_not_misread_as_legacy_or_warned(self):
        from sixcat.report import ResultFormatError, normalise_result

        document = _legacy_v1_document()
        document["overall"] = {"policy": "strict", "score": 35.0}
        warnings = io.StringIO()

        with self.assertRaisesRegex(ResultFormatError, "not an unambiguous legacy v1 result"):
            normalise_result(document, source="structured-overall", warning_stream=warnings)

        self.assertEqual(warnings.getvalue(), "")

    def test_minimal_legacy_v1_with_null_scores_warns_and_leaves_source_immutable(self):
        from sixcat.report import normalise_result

        document = {
            "model": "minimal-legacy",
            "categories": {category: None for category in CATEGORIES},
            "overall": None,
        }
        before = json.loads(json.dumps(document))
        warnings = io.StringIO()

        normalised = normalise_result(document, source="minimal-legacy", warning_stream=warnings)

        self.assertEqual(document, before)
        self.assertIn("WARNING: LEGACY V1 RESULT", warnings.getvalue())
        self.assertEqual(normalised["parser"], "v1")
        self.assertEqual(normalised["overall"], {"policy": "strict", "score": None})

    def test_stripped_current_shape_is_rejected_without_legacy_warning(self):
        from sixcat.report import ResultFormatError, normalise_result

        document = _current_document()
        document["result_schema"] = "sixcat-v2"
        document["server_props"] = {"source": "fixture"}
        document["items"] = {category: [] for category in CATEGORIES}
        for key in (
            "policy",
            "policy_source",
            "policy_probe",
            "policy_fingerprint",
            "budgets",
            "parser",
            "result_schema",
        ):
            document.pop(key)
        warnings = io.StringIO()

        with self.assertRaisesRegex(ResultFormatError, "not an unambiguous legacy v1 result"):
            normalise_result(document, source="stripped-current", warning_stream=warnings)

        self.assertEqual(warnings.getvalue(), "")


class TestComparison(unittest.TestCase):
    def test_renderer_reports_b_minus_a_with_identity_and_labelled_overall(self):
        from sixcat.report import render_compare_table

        a = _current_document(name="strict", fingerprint="aaaaaaaaaaaa")
        b = _current_document(name="vendor", fingerprint="bbbbbbbbbbbb")
        b["model"] = "other-model"
        a["categories"]["knowledge"] = 25.0
        b["categories"]["knowledge"] = 50.0
        a["overall"] = {"policy": "strict", "score": 40.0}
        b["overall"] = {"policy": "vendor", "score": 60.0}
        a["overall_label"] = "overall[strict]"
        b["overall_label"] = "overall[vendor]"

        table = render_compare_table(a, b)

        self.assertIn("A: model=current-model policy=strict parser=v3 fp=aaaaaaaaaaaa", table)
        self.assertIn("B: model=other-model policy=vendor parser=v3 fp=bbbbbbbbbbbb", table)
        knowledge = next(line for line in table.splitlines() if line.startswith("knowledge"))
        self.assertIn("25.0", knowledge)
        self.assertIn("50.0", knowledge)
        self.assertIn("+25.0", knowledge)
        self.assertIn("overall[A:strict→B:vendor]", table)
        self.assertNotRegex(table, r"(?m)^overall\s")

    def test_fingerprint_mismatch_hard_fails_unless_explicitly_allowed(self):
        from sixcat.report import PolicyMismatchError, compare_results

        a = _current_document(name="strict", fingerprint="aaaaaaaaaaaa")
        b = _current_document(name="vendor", fingerprint="bbbbbbbbbbbb")

        with self.assertRaisesRegex(PolicyMismatchError, "POLICY FINGERPRINT MISMATCH"):
            compare_results(a, b)

        table, notices = compare_results(a, b, allow_mismatch=True)
        self.assertIn("overall[A:strict→B:vendor]", table)
        self.assertTrue(any("POLICY FINGERPRINT MISMATCH" in notice for notice in notices))
        self.assertTrue(any("NOT COMPARABLE" in notice for notice in notices))
        self.assertTrue(any("POLICY LABEL MISMATCH" in notice for notice in notices))

    def test_same_profile_has_no_mismatch_notice(self):
        from sixcat.report import compare_results

        a = _current_document()
        table, notices = compare_results(a, json.loads(json.dumps(a)))

        self.assertIn("overall[A:strict→B:strict]", table)
        self.assertEqual(notices, [])

    def test_model_mismatch_is_loud_but_not_a_hard_error(self):
        from sixcat.report import compare_results

        a = _current_document()
        b = json.loads(json.dumps(a))
        b["model"] = "cross-model"

        _, notices = compare_results(a, b)

        self.assertTrue(any("MODEL MISMATCH" in notice for notice in notices))
        self.assertTrue(any("cross-model comparison" in notice for notice in notices))

    def test_run_scope_mismatch_hard_fails_unless_explicitly_allowed(self):
        from sixcat.report import RunScopeMismatchError, compare_results

        cases = []

        a = _current_document()
        b = json.loads(json.dumps(a))
        a["limit"], b["limit"] = 3, None
        cases.append(("limit", a, b))

        a = _current_document()
        b = json.loads(json.dumps(a))
        a["limit"] = b["limit"] = 20
        b["n"]["knowledge"] = 2
        b["stats"]["knowledge"]["n"] = 2
        cases.append(("n", a, b))

        a = _current_document()
        b = json.loads(json.dumps(a))
        a["limit"] = b["limit"] = 20
        a["timed_out"], b["timed_out"] = False, True
        cases.append(("timed_out", a, b))

        a = _current_document()
        b = json.loads(json.dumps(a))
        a["code_execution"], b["code_execution"] = "disabled", "host-guarded"
        cases.append(("code_execution", a, b))

        a = _current_document()
        b = json.loads(json.dumps(a))
        a["parser"], b["parser"] = "v2", "v3"
        cases.append(("parser", a, b))

        for label, left, right in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(RunScopeMismatchError, "RUN SCOPE MISMATCH"):
                    compare_results(left, right)
                table, notices = compare_results(left, right, allow_mismatch=True)
                self.assertIn("overall[A:strict→B:strict]", table)
                self.assertTrue(any("RUN SCOPE MISMATCH" in notice for notice in notices))
                self.assertTrue(any("NOT COMPARABLE" in notice for notice in notices))

    def test_both_table_scope_mismatch_hard_fails_or_renders_loud_description(self):
        from sixcat.report import RunScopeMismatchError, render_both_table

        strict = _current_document(name="strict", fingerprint="aaaaaaaaaaaa")
        vendor = _current_document(name="vendor", fingerprint="bbbbbbbbbbbb")
        vendor["n"]["knowledge"] = 2
        vendor["stats"]["knowledge"]["n"] = 2

        with self.assertRaisesRegex(RunScopeMismatchError, "RUN SCOPE MISMATCH"):
            render_both_table(strict, vendor)

        table = render_both_table(strict, vendor, allow_mismatch=True)
        self.assertIn("WARNING: RUN SCOPE MISMATCH", table)
        self.assertIn("NOT COMPARABLE", table)
        self.assertIn("overall[strict→vendor]", table)

    def test_legacy_and_current_strict_are_fingerprint_mismatched(self):
        from sixcat.report import PolicyMismatchError, normalise_result

        stderr = io.StringIO()
        legacy = normalise_result(_legacy_v1_document(), source="legacy-fixture", warning_stream=stderr)
        current = _current_document()

        from sixcat.report import compare_results

        with self.assertRaises(PolicyMismatchError):
            compare_results(legacy, current)
        self.assertIn("LEGACY V1", stderr.getvalue())
        self.assertNotEqual(legacy["policy_fingerprint"], current["policy_fingerprint"])

    def test_both_and_compare_tables_show_missing_counts_and_applicable_low_denominator(self):
        from sixcat.report import render_both_table, render_compare_table

        a = _current_document(name="strict", fingerprint="aaaaaaaaaaaa")
        b = _current_document(name="vendor", fingerprint="bbbbbbbbbbbb")
        for result in (a, b):
            for category_stats in result["stats"].values():
                category_stats.update(
                    parse_high_confidence=1,
                    parse_confidence_not_applicable=0,
                    parse_confidence_missing=0,
                )
        a["stats"]["math"] = {
            "n": 10,
            "truncated": 0,
            "parse_high_confidence": 3,
            "parse_low_confidence": 2,
            "parse_confidence_not_applicable": 4,
            "parse_confidence_missing": 1,
        }
        a["n"]["math"] = 10

        both_math = next(
            line
            for line in render_both_table(a, b, allow_mismatch=True).splitlines()
            if line.startswith("math")
        )
        compare_math = next(line for line in render_compare_table(a, b).splitlines() if line.startswith("math"))

        self.assertIn("s:missing=1/10", both_math)
        self.assertIn("s:low=2/5", both_math)
        self.assertIn("A:missing=1/10", compare_math)
        self.assertIn("A:low=2/5", compare_math)


class TestCompareCli(unittest.TestCase):
    def _write_pair(self, root: Path) -> tuple[Path, Path]:
        a = root / "a.json"
        b = root / "b.json"
        a.write_text(json.dumps(_current_document(name="strict", fingerprint="aaaaaaaaaaaa")), encoding="utf-8")
        b.write_text(json.dumps(_current_document(name="vendor", fingerprint="bbbbbbbbbbbb")), encoding="utf-8")
        return a, b

    def test_cli_mismatch_is_nonzero_and_allow_mismatch_is_zero_with_loud_warning(self):
        from sixcat.__main__ import main

        with tempfile.TemporaryDirectory() as td:
            a, b = self._write_pair(Path(td))
            blocked_out, blocked_err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(blocked_out), contextlib.redirect_stderr(blocked_err):
                blocked_rc = main(["compare", str(a), str(b)])
            allowed_out, allowed_err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(allowed_out), contextlib.redirect_stderr(allowed_err):
                allowed_rc = main(["compare", str(a), str(b), "--allow-mismatch"])

        self.assertNotEqual(blocked_rc, 0)
        self.assertIn("ERROR: POLICY FINGERPRINT MISMATCH", blocked_err.getvalue())
        self.assertEqual(allowed_rc, 0)
        self.assertIn("WARNING: POLICY FINGERPRINT MISMATCH", allowed_err.getvalue())
        self.assertIn("NOT COMPARABLE", allowed_err.getvalue())
        self.assertIn("overall[A:strict→B:vendor]", allowed_out.getvalue())

    def test_cli_same_artifact_is_zero_without_mismatch_warning(self):
        from sixcat.__main__ import main

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "same.json"
            path.write_text(json.dumps(_current_document()), encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = main(["compare", str(path), str(path)])

        self.assertEqual(rc, 0)
        self.assertNotIn("MISMATCH", stderr.getvalue())
        self.assertIn("overall[A:strict→B:strict]", stdout.getvalue())

    def test_cli_scope_mismatch_is_nonzero_and_allow_mismatch_is_loud(self):
        from sixcat.__main__ import main

        a_doc = _current_document()
        b_doc = json.loads(json.dumps(a_doc))
        a_doc["limit"], b_doc["limit"] = 3, 20
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.json", Path(td) / "b.json"
            a.write_text(json.dumps(a_doc), encoding="utf-8")
            b.write_text(json.dumps(b_doc), encoding="utf-8")
            blocked_err = io.StringIO()
            with contextlib.redirect_stderr(blocked_err):
                blocked_rc = main(["compare", str(a), str(b)])
            allowed_out, allowed_err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(allowed_out), contextlib.redirect_stderr(allowed_err):
                allowed_rc = main(["compare", str(a), str(b), "--allow-mismatch"])

        self.assertEqual(blocked_rc, 2)
        self.assertIn("ERROR: RUN SCOPE MISMATCH", blocked_err.getvalue())
        self.assertEqual(allowed_rc, 0)
        self.assertIn("WARNING: RUN SCOPE MISMATCH", allowed_err.getvalue())
        self.assertIn("NOT COMPARABLE", allowed_err.getvalue())
        self.assertIn("overall[A:strict→B:strict]", allowed_out.getvalue())

    def test_cli_malformed_current_json_fails_clearly(self):
        from sixcat.__main__ import main

        document = _current_document()
        del document["policy_source"]
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            good = Path(td) / "good.json"
            bad.write_text(json.dumps(document), encoding="utf-8")
            good.write_text(json.dumps(_current_document()), encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = main(["compare", str(bad), str(good)])

        self.assertNotEqual(rc, 0)
        self.assertIn("missing required policy metadata: policy_source", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
