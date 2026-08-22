from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, TextIO

from .score import CATEGORIES


RESULT_SCHEMA = "sixcat-v2"
PARSER_VERSION = "v4"
READABLE_PARSER_VERSIONS = frozenset({"v2", "v3", PARSER_VERSION})


class ResultFormatError(ValueError):
    """A result file cannot be safely identified or compared."""


class PolicyMismatchError(ValueError):
    """Two result profiles have fingerprints that cannot be compared by default."""


class RunScopeMismatchError(ValueError):
    """Two result profiles cover different samples or incomplete runs."""


_LEGACY_FINGERPRINT_PAYLOAD = {
    "format": "sixcat-archived-v1",
    "parser": "v1",
    "policy": "strict-assumed-not-recorded",
}
_LEGACY_FINGERPRINT = "legacy-v1-" + hashlib.sha256(
    json.dumps(_LEGACY_FINGERPRINT_PAYLOAD, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()[:12]
_CURRENT_POLICY_METADATA = ("policy", "policy_source", "policy_probe", "policy_fingerprint", "budgets")
_LEGACY_V1_KEYS = frozenset({"model", "base_url", "categories", "overall", "n"})
_CONFIDENCE_STATS = (
    "parse_high_confidence",
    "parse_low_confidence",
    "parse_confidence_not_applicable",
    "parse_confidence_missing",
)


def _validate_common(document: Mapping[str, Any], source: str) -> None:
    model = document.get("model")
    if not isinstance(model, str) or not model:
        raise ResultFormatError(f"{source}: result requires a non-empty model")
    categories = document.get("categories")
    if not isinstance(categories, Mapping):
        raise ResultFormatError(f"{source}: result requires a categories object")
    missing_categories = [category for category in CATEGORIES if category not in categories]
    if missing_categories:
        raise ResultFormatError(f"{source}: result missing categories: {', '.join(missing_categories)}")
    for category in CATEGORIES:
        score = categories[category]
        if score is not None and (not isinstance(score, (int, float)) or isinstance(score, bool)):
            raise ResultFormatError(f"{source}: category {category} score must be numeric or null")


def _normalise_overall(document: Mapping[str, Any], policy_name: str, source: str) -> dict[str, Any]:
    overall = document.get("overall")
    if isinstance(overall, Mapping):
        if overall.get("policy") != policy_name:
            raise ResultFormatError(f"{source}: overall policy label does not match policy {policy_name}")
        score = overall.get("score")
    else:
        score = overall
    if score is not None and (not isinstance(score, (int, float)) or isinstance(score, bool)):
        raise ResultFormatError(f"{source}: overall score must be numeric or null")
    return {"policy": policy_name, "score": score}


def _is_numeric_or_null(value: Any) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_unambiguous_legacy_v1(document: Mapping[str, Any]) -> bool:
    """Return true only for the small, scalar archived-v1 result shape."""
    if not {"model", "categories", "overall"}.issubset(document):
        return False
    if any(key not in _LEGACY_V1_KEYS for key in document):
        return False
    categories = document.get("categories")
    if not isinstance(categories, Mapping) or set(categories) != set(CATEGORIES):
        return False
    if not all(_is_numeric_or_null(categories[category]) for category in CATEGORIES):
        return False
    if not _is_numeric_or_null(document.get("overall")):
        return False
    if "base_url" in document and not isinstance(document["base_url"], str):
        return False
    if "n" in document and not isinstance(document["n"], Mapping):
        return False
    return True


def _normalise_current(document: Mapping[str, Any], source: str) -> dict[str, Any]:
    if "result_schema" in document and document["result_schema"] != RESULT_SCHEMA:
        raise ResultFormatError(f"{source}: current result result_schema must be {RESULT_SCHEMA}")
    missing = [key for key in _CURRENT_POLICY_METADATA if key not in document]
    if missing:
        raise ResultFormatError(f"{source}: current result missing required policy metadata: {', '.join(missing)}")
    policy = document.get("policy")
    if not isinstance(policy, Mapping) or not isinstance(policy.get("name"), str) or not policy.get("name"):
        raise ResultFormatError(f"{source}: current result policy must contain a non-empty name")
    for key in ("policy_source", "policy_probe", "policy_fingerprint"):
        if not isinstance(document.get(key), str) or not document[key]:
            raise ResultFormatError(f"{source}: current result {key} must be a non-empty string")
    budgets = document.get("budgets")
    if not isinstance(budgets, Mapping) or any(category not in budgets for category in CATEGORIES):
        raise ResultFormatError(f"{source}: current result budgets must contain all six categories")
    if document.get("parser") not in READABLE_PARSER_VERSIONS:
        readable = ", ".join(sorted(READABLE_PARSER_VERSIONS))
        raise ResultFormatError(f"{source}: current result parser must be one of {readable}")
    stats = document.get("stats")
    if not isinstance(stats, Mapping):
        raise ResultFormatError(f"{source}: current result requires per-category stats")
    marked_v2 = document.get("result_schema") == RESULT_SCHEMA
    if marked_v2 and document.get("code_execution") not in {"disabled", "host-guarded"}:
        raise ResultFormatError(
            f"{source}: current result code_execution must be 'disabled' or 'host-guarded'"
        )
    for category in CATEGORIES:
        category_stats = stats.get(category)
        if not isinstance(category_stats, Mapping):
            raise ResultFormatError(f"{source}: current result missing stats for {category}")
        required_stats = ("n", "truncated", *_CONFIDENCE_STATS) if marked_v2 else (
            "truncated",
            "parse_low_confidence",
        )
        missing_stats = [key for key in required_stats if key not in category_stats]
        if missing_stats:
            raise ResultFormatError(
                f"{source}: current result stats for {category} missing {', '.join(missing_stats)}"
            )
        if marked_v2:
            for key in required_stats:
                if not _is_non_negative_int(category_stats[key]):
                    raise ResultFormatError(
                        f"{source}: current result stats for {category} {key} must be a non-negative integer"
                    )
            n = category_stats["n"]
            confidence_total = sum(category_stats[key] for key in _CONFIDENCE_STATS)
            if confidence_total != n:
                raise ResultFormatError(
                    f"{source}: confidence buckets for {category} must sum to n={n}; got {confidence_total}"
                )
    if not isinstance(document.get("overall_flags"), list):
        raise ResultFormatError(f"{source}: current result requires overall_flags list")

    normalised = copy.deepcopy(dict(document))
    policy_name = str(policy["name"])
    normalised["overall"] = _normalise_overall(document, policy_name, source)
    expected_label = f"overall[{policy_name}]"
    supplied_label = document.get("overall_label")
    if supplied_label is None:
        if not isinstance(document.get("overall"), Mapping):
            raise ResultFormatError(f"{source}: numeric overall requires explicit overall_label {expected_label}")
        # Phase 4 parser-v2 artifacts predate the explicit label field. Keep the file
        # immutable and add the deterministic label only to this in-memory view.
        normalised["overall_label"] = expected_label
    elif supplied_label != expected_label:
        raise ResultFormatError(f"{source}: overall_label must be {expected_label}")
    return normalised


def _normalise_legacy(document: Mapping[str, Any], source: str, warning_stream: TextIO) -> dict[str, Any]:
    print(
        "WARNING: LEGACY V1 RESULT: "
        f"{source} has no policy metadata; interpreting as policy=strict and parser=v1. "
        f"This in-memory assumption is not comparable to current strict/parser-{PARSER_VERSION}; "
        "the archive file is unchanged.",
        file=warning_stream,
    )
    normalised = copy.deepcopy(dict(document))
    normalised["policy"] = {
        "name": "strict",
        "legacy_assumption": True,
        "parser": "v1",
    }
    normalised["policy_source"] = "legacy-v1-assumption"
    normalised["policy_probe"] = "not-recorded-v1"
    normalised["policy_fingerprint"] = _LEGACY_FINGERPRINT
    normalised["budgets"] = None
    normalised["parser"] = "v1"
    normalised["overall"] = _normalise_overall(document, "strict", source)
    normalised["overall_label"] = "overall[strict;parser=v1;legacy-assumed]"
    normalised.setdefault("overall_flags", [])
    n_by_category = normalised.get("n") if isinstance(normalised.get("n"), Mapping) else {}
    source_stats = normalised.get("stats") if isinstance(normalised.get("stats"), Mapping) else {}
    normalised["stats"] = {
        category: {
            "n": (source_stats.get(category) or {}).get("n", n_by_category.get(category, 0)),
            "truncated": (source_stats.get(category) or {}).get("truncated"),
            "parse_low_confidence": (source_stats.get(category) or {}).get("parse_low_confidence"),
        }
        for category in CATEGORIES
    }
    normalised.setdefault("n", {category: 0 for category in CATEGORIES})
    return normalised


def normalise_result(
    document: Mapping[str, Any],
    *,
    source: str = "<memory>",
    warning_stream: TextIO | None = None,
) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise ResultFormatError(f"{source}: result JSON root must be an object")
    _validate_common(document, source)
    has_policy = "policy" in document
    if not has_policy:
        if not _is_unambiguous_legacy_v1(document):
            raise ResultFormatError(
                f"{source}: not an unambiguous legacy v1 result; expected only model, optional base_url, "
                "six numeric/null categories, numeric/null overall, and optional n"
            )
        return _normalise_legacy(document, source, warning_stream or sys.stderr)
    return _normalise_current(document, source)


def load_result(path: str | Path, *, warning_stream: TextIO | None = None) -> dict[str, Any]:
    result_path = Path(path)
    try:
        document = json.loads(result_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ResultFormatError(f"cannot read result {result_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ResultFormatError(f"malformed JSON in result {result_path}: {exc}") from exc
    return normalise_result(document, source=str(result_path), warning_stream=warning_stream)


def _policy_name(result: Mapping[str, Any]) -> str:
    policy = result.get("policy") or {}
    name = policy.get("name") if isinstance(policy, Mapping) else None
    if not isinstance(name, str) or not name:
        raise ValueError("cannot render a bare overall without a policy label")
    return name


def _overall_score(result: Mapping[str, Any]) -> float | None:
    overall = result.get("overall")
    if isinstance(overall, Mapping):
        score = overall.get("score")
    else:
        score = overall
    return score if isinstance(score, (int, float)) and not isinstance(score, bool) else None


def _score_cell(value: Any) -> str:
    if value is None:
        return "n/a"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"score must be numeric or null, got {value!r}")
    return f"{value:.1f}"


def _delta_cell(a: Any, b: Any) -> str:
    if a is None or b is None:
        return "n/a"
    if not isinstance(a, (int, float)) or isinstance(a, bool):
        raise ValueError(f"score must be numeric or null, got {a!r}")
    if not isinstance(b, (int, float)) or isinstance(b, bool):
        raise ValueError(f"score must be numeric or null, got {b!r}")
    return f"{b - a:+.1f}"


def _category_flags(result: Mapping[str, Any], category: str) -> list[str]:
    stats = result.get("stats") or {}
    category_stats = stats.get(category) or {}
    flags: list[str] = []
    truncated = category_stats.get("truncated") or 0
    high = category_stats.get("parse_high_confidence") or 0
    low = category_stats.get("parse_low_confidence") or 0
    not_applicable = category_stats.get("parse_confidence_not_applicable") or 0
    n = category_stats.get("n")
    if n is None:
        n = (result.get("n") or {}).get(category, 0)
    missing = category_stats.get("parse_confidence_missing")
    if missing is None:
        # Pre-marker Phase 3/4 artifacts did not persist all four buckets. Surface the
        # unaccounted rows rather than silently treating them as high confidence.
        missing = max(n - high - low - not_applicable, 0)
    if truncated:
        flags.append(f"trunc={truncated}")
    if missing:
        flags.append(f"missing={missing}/{n}")
    applicable = high + low
    if applicable and low / applicable > 0.2:
        flags.append(f"low={low}/{applicable}")
    return flags


def render_both_table(
    strict: Mapping[str, Any],
    vendor: Mapping[str, Any],
    *,
    allow_mismatch: bool = False,
) -> str:
    """Render one deterministic vendor-minus-strict profile delta table."""
    scope_mismatches = _run_scope_mismatches(strict, vendor)
    warning_lines: list[str] = []
    if scope_mismatches:
        mismatch = "RUN SCOPE MISMATCH: " + "; ".join(scope_mismatches)
        if not allow_mismatch:
            raise RunScopeMismatchError(mismatch)
        warning_lines = [
            "WARNING: " + mismatch + "; SCORES ARE NOT COMPARABLE. Descriptive delta only.",
            "",
        ]
    strict_name = _policy_name(strict)
    vendor_name = _policy_name(vendor)
    strict_model = strict.get("model")
    vendor_model = vendor.get("model")
    model_line = str(strict_model) if strict_model == vendor_model else f"strict={strict_model} vendor={vendor_model}"
    lines = warning_lines + [
        "=== STRICT vs VENDOR DELTA (vendor - strict) ===",
        f"model: {model_line}",
        f"strict: {strict_name} fp={strict.get('policy_fingerprint')} source={strict.get('policy_source')}",
        f"vendor: {vendor_name} fp={vendor.get('policy_fingerprint')} source={vendor.get('policy_source')}",
        "",
        f"{'category':<26} {'strict':>8} {'vendor':>8} {'delta':>8} {'n s/v':>9}  flags",
        "-" * 86,
    ]
    strict_categories = strict.get("categories") or {}
    vendor_categories = vendor.get("categories") or {}
    strict_n = strict.get("n") or {}
    vendor_n = vendor.get("n") or {}
    for category in CATEGORIES:
        a = strict_categories.get(category)
        b = vendor_categories.get(category)
        flags = [f"s:{flag}" for flag in _category_flags(strict, category)]
        flags.extend(f"v:{flag}" for flag in _category_flags(vendor, category))
        lines.append(
            f"{category:<26} {_score_cell(a):>8} {_score_cell(b):>8} {_delta_cell(a, b):>8} "
            f"{str(strict_n.get(category, 0)) + '/' + str(vendor_n.get(category, 0)):>9}  {', '.join(flags) or '-'}"
        )
    lines.append("-" * 86)
    a_overall = _overall_score(strict)
    b_overall = _overall_score(vendor)
    overall_flags = [f"s:{flag}" for flag in (strict.get("overall_flags") or [])]
    overall_flags.extend(f"v:{flag}" for flag in (vendor.get("overall_flags") or []))
    label = f"overall[{strict_name}→{vendor_name}]"
    lines.append(
        f"{label:<26} {_score_cell(a_overall):>8} {_score_cell(b_overall):>8} "
        f"{_delta_cell(a_overall, b_overall):>8} {'-':>9}  {', '.join(overall_flags) or '-'}"
    )
    return "\n".join(lines)


def render_compare_table(a: Mapping[str, Any], b: Mapping[str, Any]) -> str:
    """Render B-minus-A deltas with explicit model, parser, and policy identity."""
    a_name = _policy_name(a)
    b_name = _policy_name(b)
    lines = [
        "=== SIXCAT COMPARE (B - A) ===",
        f"A: model={a.get('model')} policy={a_name} parser={a.get('parser')} "
        f"fp={a.get('policy_fingerprint')} source={a.get('policy_source')}",
        f"B: model={b.get('model')} policy={b_name} parser={b.get('parser')} "
        f"fp={b.get('policy_fingerprint')} source={b.get('policy_source')}",
        "",
        f"{'category':<30} {'A':>8} {'B':>8} {'B-A':>8} {'n A/B':>9}  flags",
        "-" * 90,
    ]
    a_categories = a.get("categories") or {}
    b_categories = b.get("categories") or {}
    a_n = a.get("n") or {}
    b_n = b.get("n") or {}
    for category in CATEGORIES:
        a_score = a_categories.get(category)
        b_score = b_categories.get(category)
        flags = [f"A:{flag}" for flag in _category_flags(a, category)]
        flags.extend(f"B:{flag}" for flag in _category_flags(b, category))
        lines.append(
            f"{category:<30} {_score_cell(a_score):>8} {_score_cell(b_score):>8} "
            f"{_delta_cell(a_score, b_score):>8} "
            f"{str(a_n.get(category, 0)) + '/' + str(b_n.get(category, 0)):>9}  "
            f"{', '.join(flags) or '-'}"
        )
    lines.append("-" * 90)
    a_overall = _overall_score(a)
    b_overall = _overall_score(b)
    overall_flags = [f"A:{flag}" for flag in (a.get("overall_flags") or [])]
    overall_flags.extend(f"B:{flag}" for flag in (b.get("overall_flags") or []))
    label = f"overall[A:{a_name}→B:{b_name}]"
    lines.append(
        f"{label:<30} {_score_cell(a_overall):>8} {_score_cell(b_overall):>8} "
        f"{_delta_cell(a_overall, b_overall):>8} {'-':>9}  {', '.join(overall_flags) or '-'}"
    )
    return "\n".join(lines)


def _run_scope_mismatches(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    """Return scope differences that make score deltas non-comparable."""
    mismatches: list[str] = []
    if a.get("parser") != b.get("parser"):
        mismatches.append(f"parser A={a.get('parser')!r} B={b.get('parser')!r}")
    if ("limit" in a) != ("limit" in b) or a.get("limit") != b.get("limit"):
        mismatches.append(f"limit A={a.get('limit')!r} B={b.get('limit')!r}")
    for field in ("limit_scope", "selection_profile", "selection_fingerprint"):
        if (field in a) != (field in b) or a.get(field) != b.get(field):
            mismatches.append(f"{field} A={a.get(field)!r} B={b.get(field)!r}")
    if ("code_execution" in a) != ("code_execution" in b) or a.get("code_execution") != b.get("code_execution"):
        mismatches.append(
            f"code_execution A={a.get('code_execution')!r} B={b.get('code_execution')!r}"
        )

    a_n = a.get("n") if isinstance(a.get("n"), Mapping) else {}
    b_n = b.get("n") if isinstance(b.get("n"), Mapping) else {}
    differing_counts = [
        f"{category}={a_n.get(category)!r}/{b_n.get(category)!r}"
        for category in CATEGORIES
        if a_n.get(category) != b_n.get(category)
    ]
    if differing_counts:
        mismatches.append("n " + ", ".join(differing_counts))

    if bool(a.get("timed_out")) or bool(b.get("timed_out")):
        mismatches.append(f"timed_out A={bool(a.get('timed_out'))} B={bool(b.get('timed_out'))}")
    return mismatches


def compare_results(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    *,
    allow_mismatch: bool = False,
) -> tuple[str, list[str]]:
    """Check comparability and return a labelled table plus loud notices."""
    a_name = _policy_name(a)
    b_name = _policy_name(b)
    a_fp = a.get("policy_fingerprint")
    b_fp = b.get("policy_fingerprint")
    notices: list[str] = []
    if a_fp != b_fp:
        mismatch = (
            "POLICY FINGERPRINT MISMATCH: "
            f"A policy={a_name} fp={a_fp}; B policy={b_name} fp={b_fp}"
        )
        if not allow_mismatch:
            raise PolicyMismatchError(mismatch + "; pass --allow-mismatch only for a non-comparable descriptive delta")
        notices.append(
            "WARNING: "
            + mismatch
            + "; SETTINGS ARE NOT COMPARABLE. Deltas below are descriptive only because --allow-mismatch was explicit."
        )
    scope_mismatches = _run_scope_mismatches(a, b)
    if scope_mismatches:
        mismatch = "RUN SCOPE MISMATCH: " + "; ".join(scope_mismatches)
        if not allow_mismatch:
            raise RunScopeMismatchError(
                mismatch + "; pass --allow-mismatch only for a non-comparable descriptive delta"
            )
        notices.append(
            "WARNING: "
            + mismatch
            + "; SCORES ARE NOT COMPARABLE. Deltas below are descriptive only because --allow-mismatch was explicit."
        )
    if a_name != b_name:
        notices.append(f"WARNING: POLICY LABEL MISMATCH: A={a_name} B={b_name}")
    if a.get("parser") != b.get("parser"):
        notices.append(
            f"WARNING: PARSER MISMATCH: A={a.get('parser')} B={b.get('parser')}; scores are NOT COMPARABLE"
        )
    if a.get("model") != b.get("model"):
        notices.append(
            f"NOTICE: MODEL MISMATCH: A={a.get('model')} B={b.get('model')} (cross-model comparison)"
        )
    return render_compare_table(a, b), notices
