# SixCat 0.6.0 — fast, time-bounded, first-response evaluation

The standard benchmark is still 120 items, 20 per category. No larger default suite, mandatory model download, LLM judge, or always-on repeated run was added. Full mode selects 884 items and remains optional.

## Execution

- One bounded concurrent pool across the six categories. Round-robin dispatch preserves each category's frozen hardest-first order and samples every category earlier.
- `--concurrency N` controls active work without eagerly queuing a whole dataset. The default remains 1 for compatibility and memory safety; use 2 or 4 when your server supports it.
- One monotonic deadline covers preflight, HTTP/stdio requests, and code execution. `--policy both` shares that deadline rather than multiplying it.
- Pooled HTTPX transport has a total deadline and a response-size limit. Stdio gains a real timeout and refuses reuse after desynchronization. Stdio remains serial.
- Transport failures and interrupted requests are unscored, not model FAILs. A returned completion interrupted during local grading is journaled and reused on resume.

## Scoring and provenance

- Parser v5: bounded MC tokens, actual choice validation, ambiguous-answer status, unterminated-think stripping, and complete numeric-expression parsing.
- Typed tool comparison distinguishes JSON booleans from numbers.
- First scored responses are immutable. Failure retries have a separate latest-attempt diagnostic; they cannot inflate the headline score.
- Benchmark manifests hash selected keys, data, scorer sources and tool schemas. Text hashes normalize line endings.
- Resume checks exact endpoints and advertised runtime identity. A loopback port may vary only when matching verified upstream identity was recorded; otherwise the exact endpoint is required.
- `--artifact-id` records operator-provided model/quant identity. Advertised metadata is not cryptographic proof of served weights.
- Result loading checks score ranges, finite values, counts, unique selected keys, manifest consistency and the overall calculation.

## Reliability and telemetry

- Torn final JSONL bytes are backed up and repaired before append. Interior corruption fails closed. Journals have single-writer locks; final JSON writes are atomic.
- Code and Tools now use the same completion receipt format as all other categories.
- Per-request speed and actual concurrent session throughput have separate fields, coverage and latency diagnostics. Resume does not count cached generations as new throughput.
- Host code execution gains bounded stdout and best-effort Unix resource caps. It is still not a security sandbox.

## Optional analysis

- Compare lists exact regressions and improvements and computes a category-stratified paired bootstrap interval. Mismatched runs receive descriptive-only treatment.
- `repeat` explicitly requests a fresh matched-seed series within one total budget.
- `rescore` grades saved first responses offline, preserving source provenance and refusing dataset drift or unknown legacy attempt provenance.
- `export-evalplus` exports saved coding solutions only. It neither runs EvalPlus nor labels a 20-item subset as full HumanEval+.

## CI

Python 3.11–3.14 Linux testing plus Windows/macOS, bounded unit and loopback integration tests, an 85% coverage floor, workflow security validation, wheel/sdist builds and installed-wheel smoke tests. Actions are pinned to full commit SHAs and run with read-only repository permissions. Reports, dependencies and build artifacts are retained.

## Migration

Use fresh `--out`/`--log` paths for 0.6.0. Parser-v4 journals do not resume into v5, and old scores are not silently comparable. Existing v2/v3/v4 result files remain readable under their original identities. Later failure retries no longer replace the first-response overall. Any old score assembled by selectively retrying failures remains a legacy latest-attempt result.

All previous release notes are preserved unchanged in [RELEASE_NOTES-v0.5.1.md](RELEASE_NOTES-v0.5.1.md). Original measured examples and caveats are preserved in [README-v0.5.1.md](README-v0.5.1.md).
