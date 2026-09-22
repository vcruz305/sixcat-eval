# SixCat 0.7.0 — adaptive concurrency and speed telemetry

### Workload-specific speed suite

- `sixcat speed` with no profile now runs **decode + balanced + prefill** in one command.
- Decode uses a short prompt and long generation; its headline is the **single-stream C=1** sustained decode distribution so concurrency batching cannot make the model look slower than its true per-stream generation capability.
- Balanced uses a mixed workload and remains the primary concurrency-knee / realistic serving-throughput view.
- Prefill uses a long prompt and short generation so prompt ingestion is not hidden behind a long decode tail.
- Curve and confirmation use the **same workload** for each profile.
- Added decode p50/p95/max and p90 best-sustained headline reporting.
- Aggregate output throughput is explicitly labeled as including prefill, queueing and failure wall time.
- Concurrency levels below the configurable success threshold are excluded from the knee and the report includes `max_usable_concurrency`.
- Missing native server/provider timings now print an explicit "server metrics unavailable for this route" reason instead of unexplained nulls.
- `--profile decode|balanced|prefill|custom|all` selects workloads; `all` is the default.
- Custom prompt/output lengths remain available through `--profile custom --prompt-words N --max-tokens N`.
- Speed JSON now ends with a compact `summary` object plus a Markdown-ready `copy_paste` block for decode, prefill, balanced serving, TTFT, and max usable concurrency.

0.7.0 extends SixCat's "finish useful work quickly" philosophy to the serving layer. Standard scoring remains 120 difficult items, but an optional unscored calibration phase can now discover the throughput knee of an already-running inference server before the benchmark starts.

## Auto-concurrency

- New `--auto-concurrency` mode for normal scored runs.
- Default curve: concurrency 1, 2, 4, 8.
- Synthetic unscored prompts are used, with unique leading markers to avoid warming the actual benchmark questions or creating a large shared prefix-cache advantage.
- Selection method: choose the smallest concurrency reaching at least 90% of measured peak aggregate output throughput.
- Falls back to request throughput when streaming token usage is unavailable.
- Rejects concurrency levels with poor request-success rates.
- Calibration shares the same invocation deadline as the 30-minute benchmark.
- Curve, peak, recommendation, selection metric and confidence are stored in the final scored result.

## New `sixcat speed` command

- Standalone serving-speed benchmark with no quality scoring.
- Can discover a curve automatically or confirm a fixed `--concurrency N`.
- Streaming measurement of client-observed TTFT.
- TTFT, end-to-end latency and TPOT p50/p95/p99.
- Aggregate output tokens/second and requests/second.
- Effective client-observed prefill and decode rates.
- Native server prefill/decode timing when exposed.
- Provider TTFT, queue latency and ITL when exposed.
- JSON output for automation and release receipts.
- p99 is explicitly flagged as low-sample when fewer than 100 confirmation requests are used.
- One compatibility fallback handles OpenAI-compatible servers that stream but do not support `stream_options.include_usage`.

## Measurement semantics

- Client TTFT includes client/network transport, scheduler queueing and prefill.
- `effective_prefill_tps` is intentionally not mislabeled as pure model prefill throughput.
- Provider/server timing fields remain separate from client-observed measurements.
- Effective decode TPS is computed after the first streamed output token when completion token usage is available.
- The curve is designed to identify the throughput knee, not to claim that larger concurrency always means faster serving.

## Why the knee instead of peak

For a throughput-oriented 120-question evaluation, the absolute highest measured concurrency may only add a few percent throughput while significantly worsening TTFT, memory/KV pressure, and per-request latency. Choosing the smallest level within 90% of peak is a stable default; operators can change `--calibration-knee-fraction` or the candidate list explicitly.

## Compatibility

- Existing explicit `--concurrency N` behavior remains unchanged.
- `--auto-concurrency` is OpenAI-compatible HTTP only; stdio stays serial.
- The calibration phase never changes or restarts the inference server. It only changes the number of simultaneous client requests.
- v0.6 result files remain readable.

---

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
