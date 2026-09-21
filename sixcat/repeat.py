"""Explicit matched-seed repeats; never expands the default 120-item run."""
from __future__ import annotations
import argparse
import math
import statistics
from pathlib import Path

from .journal import TimeBudget
from .report import load_result
from .storage import atomic_write_json


def main(argv: list[str]) -> int:
    from .__main__ import _run_main
    parser = argparse.ArgumentParser(prog="sixcat repeat", description="Optional fresh matched-seed runs sharing ONE total time budget.")
    parser.add_argument("--seeds", required=True, help="Distinct comma-separated integer seeds, e.g. 1,2,3")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-minutes", type=float, default=30)
    parser.add_argument("run_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        seeds = [int(value.strip()) for value in args.seeds.split(",")]
    except ValueError:
        parser.error("--seeds must contain comma-separated integers")
    if not seeds or len(seeds) != len(set(seeds)):
        parser.error("seeds must be nonempty and distinct")
    if not math.isfinite(args.max_minutes) or args.max_minutes < 0:
        parser.error("--max-minutes must be finite and non-negative")
    forwarded = args.run_args[1:] if args.run_args[:1] == ["--"] else args.run_args
    forbidden = {"--seed", "--out", "--log", "--max-minutes", "--retry", "--no-resume", "--transport"}
    if any(token.split("=", 1)[0] in forbidden for token in forwarded):
        parser.error("seed/output/retry/transport/time controls belong to repeat; only HTTP runs are supported")
    if any(token == "--policy=both" or (token == "--policy" and forwarded[i+1:i+2] == ["both"])
           for i, token in enumerate(forwarded)):
        parser.error("choose one sampling policy per repeat series")
    paths = [args.out_dir / f"seed-{seed}.json" for seed in seeds]
    summary_path = args.out_dir / "repeat.json"
    if summary_path.exists() or any(path.exists() or path.with_suffix(".jsonl").exists() for path in paths):
        parser.error("use an unused output directory; repeats do not overwrite previous generations")
    budget = TimeBudget(None if args.max_minutes == 0 else args.max_minutes * 60)
    runs = []
    code = 0
    for seed, path in zip(seeds, paths):
        if budget.expired():
            break
        remaining = budget.remaining()
        run_code = _run_main([*forwarded, "--seed", str(seed), "--out", str(path),
                             "--max-minutes", str(0 if remaining is None else remaining / 60)])
        code = max(code, run_code)
        if path.exists():
            result = load_result(path)
            runs.append({"seed": seed, "path": str(path), "complete": result["complete"],
                         "overall": result["overall"]["score"],
                         "benchmark_fingerprint": result["benchmark_fingerprint"]})
    values = [r["overall"] for r in runs if r["complete"] and r["overall"] is not None]
    summary = {"kind": "sixcat-repeat-series", "requested_seeds": seeds, "runs": runs,
               "total_time_budget_minutes": args.max_minutes, "complete_runs": len(values),
               "mean_overall_complete_runs": statistics.mean(values) if values else None,
               "stdev_overall_complete_runs": statistics.stdev(values) if len(values) > 1 else None,
               "caveat": "Descriptive generation variability. Compare the same seeds and settings for both models; endpoints may ignore seeds."}
    atomic_write_json(summary_path, summary)
    print(f"repeat summary: {summary_path}; {len(values)}/{len(seeds)} complete runs")
    return code
