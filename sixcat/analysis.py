"""Paired, category-stratified comparison of the SAME saved first responses.

The interval describes resampling this frozen challenge set, not uncertainty
about all LLM tasks or generation variability. No model calls and no SciPy
runtime dependency. Percentile paired bootstrap preserves category weights.
"""
from __future__ import annotations

import random
from .score import CATEGORIES, _percentile


def _key(row):
    return str(row.get("key") or row.get("id") or row.get("task_id") or "")


def paired_comparison(a: dict, b: dict, *, samples: int = 2000, seed: int = 0) -> dict:
    if not 100 <= samples <= 100000:
        raise ValueError("bootstrap samples must be between 100 and 100000")
    strata, changes, counts = [], [], {}
    for category in CATEGORIES:
        aa = (a.get("items") or {}).get(category, [])
        bb = (b.get("items") or {}).get(category, [])
        left, right = {_key(r): r for r in aa}, {_key(r): r for r in bb}
        if len(left) != len(aa) or len(right) != len(bb) or set(left) != set(right) or "" in left or "" in right:
            raise ValueError(f"paired comparison requires identical unique item keys: {category}")
        differences = []
        counts[category] = {"pairs": len(left), "improved": 0, "regressed": 0, "unchanged": 0}
        for key in sorted(left):
            l, r = left[key], right[key]
            if type(l.get("ok")) is not bool or type(r.get("ok")) is not bool:
                raise ValueError("paired comparison requires scored Boolean outcomes")
            delta = int(r["ok"]) - int(l["ok"])
            label = "improved" if delta > 0 else "regressed" if delta < 0 else "unchanged"
            counts[category][label] += 1
            differences.append(delta)
            if delta:
                changes.append({"category": category, "key": key, "change": label,
                                "a_ok": l["ok"], "b_ok": r["ok"],
                                "a_pred": l.get("pred"), "b_pred": r.get("pred")})
        if differences:
            strata.append(differences)
    if not strata:
        raise ValueError("no paired item receipts are available")
    point = 100 * sum(sum(s) / len(s) for s in strata) / len(strata)
    rng = random.Random(seed)
    distribution = [100 * sum(sum(rng.choices(s, k=len(s))) / len(s) for s in strata) / len(strata)
                    for _ in range(samples)]
    low, high = _percentile(distribution, .025), _percentile(distribution, .975)
    return {"method": "paired-category-stratified-percentile-bootstrap", "samples": samples,
            "seed": seed, "delta_points": point, "interval_95": [low, high],
            "degenerate": low == high, "categories": counts, "changes": changes,
            "caveat": "Conditional on this fixed challenge set; not generation variability or full-benchmark generalization."}


def render_paired(result: dict) -> str:
    low, high = result["interval_95"]
    lines = ["", "PAIRED FIRST-RESPONSE CHANGES (B - A)",
             f"delta {result['delta_points']:+.2f} points; 95% paired bootstrap [{low:+.2f}, {high:+.2f}]",
             f"resamples={result['samples']} seed={result['seed']}"]
    for cat, counts in result["categories"].items():
        if counts["pairs"]:
            lines.append(f"{cat}: {counts['pairs']} pairs; +{counts['improved']} improved; -{counts['regressed']} regressed")
    for row in result["changes"]:
        lines.append(f"  {row['change'].upper()} {row['category']}/{row['key']}")
    if result["degenerate"]:
        lines.append("Degenerate interval: these saved outcomes provide no within-set resampling spread; this does NOT establish zero uncertainty.")
    lines.append(result["caveat"])
    return "\n".join(lines)
