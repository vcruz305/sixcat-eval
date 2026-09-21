<img width="1774" height="887" alt="SixCat benchmark dashboard" src="assets/sixcat-readme-header-v0.2.0.png" />

# sixcat-eval

**120 challenging questions. Six categories. One first-response score. A 30-minute budget.**

SixCat is a daily regression check for local models and quantizations, not another benchmark that takes all afternoon. Standard mode keeps the frozen `challenge-v1` selection: 20 items in each category, with the hardest-first ordering retained within each category. Version **0.6.0** dispatches those categories round-robin through one bounded concurrent pool so a time-limited run does not finish Knowledge and Math while never reaching Tools.

## Run the short benchmark

Python 3.11 or newer:

```bash
git clone https://github.com/vcruz305/sixcat-eval
cd sixcat-eval
python -m pip install -e .

python -m sixcat \
  --base-url http://127.0.0.1:8085/v1 \
  --model my-model \
  --artifact-id my-model-Q4-release-1 \
  --policy strict \
  --concurrency 4 \
  --max-minutes 30 \
  --out results/my-model-q4.json
```

No `--full` or extra dataset download is needed. This requests **120 scored items**, plus one unscored thinking probe. `--concurrency 1` remains the conservative default. Use 2 for a memory-tight server or 4 when the endpoint has parallel capacity. More concurrent requests are not guaranteed to help every model or GPU, and increase simultaneous KV-cache demand. SixCat does not resize, restart, or reconfigure your server.

For llama.cpp, provision enough server parallel slots (`--parallel` / `-np`). For vLLM, its scheduler must have capacity for the requested sequences (`--max-num-seqs`), with sufficient KV-cache headroom. Check the runtime's own configuration rather than assuming four clients means four GPU lanes. [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) · [vLLM serving documentation](https://docs.vllm.ai/en/latest/cli/serve/).

The time limit is a **shared monotonic invocation deadline**, including preflight and active requests. HTTP requests have total deadlines, so a slow-drip response cannot hold the client indefinitely. After the deadline, queued work is not started and interrupted items remain unscored. Local cleanup and saving receipts can take a little longer. Disconnecting a request does not guarantee that a remote server cancels GPU work. A 30-minute budget also cannot guarantee that any particular model finishes all 120 items.

## Adaptive concurrency and serving-speed benchmark

SixCat 0.7 can measure an already-running inference server before the scored run and select a concurrency level automatically.

```bash
python -m sixcat \
  --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_MODEL \
  --policy strict \
  --auto-concurrency \
  --max-minutes 30 \
  --out results/model.json
```

The default discovery curve tests **1, 2, 4, and 8** in-flight requests with unscored synthetic prompts. It does not send SixCat benchmark questions during calibration. For each level it measures aggregate output throughput, request rate, client-observed TTFT, end-to-end latency, effective prefill/decode rates, and provider/server timings when available.

The default recommendation is the **smallest concurrency that reaches at least 90% of the measured peak aggregate throughput**. This deliberately chooses the throughput knee instead of blindly selecting the largest or absolute-peak concurrency, reducing unnecessary TTFT/KV-cache pressure for tiny marginal gains. The curve counts against the same 30-minute invocation budget.

Customize the search when useful:

```bash
python -m sixcat \
  --model YOUR_MODEL \
  --auto-concurrency \
  --concurrency-candidates 1,2,4,8,16 \
  --calibration-seconds 90 \
  --calibration-knee-fraction 0.90
```

### Speed-only mode

For users who only want to validate serving performance, `sixcat speed` runs no scored benchmark:

```bash
python -m sixcat speed \
  --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_MODEL \
  --candidates 1,2,4,8 \
  --samples 32 \
  --out results/model-speed.json
```

It first discovers the concurrency curve, then performs a confirmation run at the recommended concurrency. You can skip discovery and test a fixed level with `--concurrency 4`.

Reported metrics include:

- **client TTFT p50/p95/p99** — request start to first streamed output token; this includes network, queueing, and prefill;
- **end-to-end latency p50/p95/p99**;
- **TPOT p50/p95/p99** — client-observed time per output token after the first token;
- **aggregate output tok/s** across all concurrent requests;
- **request rate**;
- **effective prefill tok/s** — prompt tokens / client TTFT, explicitly labeled effective because it includes queue/network overhead;
- **effective decode tok/s** from streamed completion tokens and decode wall time;
- **server prefill/decode tok/s** when the provider exposes native timing fields;
- **provider TTFT/queue/ITL** when the endpoint exposes per-request metrics.

llama.cpp currently exposes prompt/decode timing fields and streamed usage through its OpenAI-compatible server, while current vLLM exposes serving metrics such as TTFT, inter-token latency, prefill time, and decode time through its metrics/per-request instrumentation. SixCat keeps client-observed and provider-native measurements separate instead of pretending they are interchangeable.

With fewer than 100 confirmation requests, the report marks p99 as a low-sample empirical/interpolated tail estimate. Use `--samples 100` or more when p99 itself is an important acceptance criterion.

## Score contract

| Category | Source | Standard count | Verdict |
|---|---|---:|---|
| Knowledge | tinyMMLU, tinyARC, tinyHellaSwag, tinyWinogrande | 20 total | Presented-choice letter match |
| Math | tinyGSM8K | 20 | Exact normalized final number |
| Truth | tinyTruthfulQA MC1 | 20 | Presented-choice letter match |
| Instruct | IFEval-100 | 20 | All item constraints pass |
| Code | HumanEval | 20 | One saved generation, guarded local checker |
| Tools | Structured function-call challenges | 20 | Typed arguments, exact order/count, or abstention |

Each category is `100 * correct / scored`. Overall is the unweighted mean of nonempty category scores. **A partial result is labeled incomplete and is not comparable by default.** Missing items are not silently counted as model failures. The three no-tool challenges test abstention, not the correctness of their free-text answers.

Parser **v5** rejects option letters outside the displayed choices, does not confuse words such as “definitely” with option D, marks conflicting answers ambiguous, strips incomplete inline thinking, and parses full supported numeric expressions instead of accepting their prefixes. Tool arguments distinguish JSON booleans from numbers. These results are not silently comparable with parser-v4 results.

### First responses stay first

The headline score never improves merely because you selectively reran failures. The journal keeps every attempt and the first scored response separately. Later samples are displayed only in a **latest-attempt diagnostic, not pass@1**. Network failures do not become FAILs. When an answer arrived but its local grader was interrupted, resume reuses that saved completion rather than obtaining a new one.

```bash
# Continue unfinished items, retaining all original scored answers.
python -m sixcat \
  --base-url http://127.0.0.1:8085/v1 --model my-model \
  --artifact-id my-model-Q4-release-1 --policy strict --concurrency 4 \
  --max-minutes 30 --out results/my-model-q4.json --retry remaining
```

`--retry failed` and `--retry incomplete` still exist for diagnostics. They do not replace first-response headline verdicts. `python -m sixcat retry-plan RESULT.json --retry remaining --json` reconstructs the model, endpoint, policy, budgets, artifact identity and relevant options. Old journals need fresh output paths because the scoring and identity contracts changed.

## Identity, recovery, and auditability

Every result includes selected item keys, hashes of dataset contents and scorer sources, policy fingerprint, parser version, raw answers, exact wire payloads without authorization headers, and available runtime identity. UTF-8 text hashes normalize line endings so a Windows checkout is not a different benchmark.

Different localhost ports are **not** automatically the same endpoint. A Hermes proxy may change its ephemeral port only when the journal recorded matching verified upstream route metadata; otherwise resume requires the exact endpoint or a fresh journal. `--artifact-id` records an operator-provided model revision, quantization name or hash; SixCat cannot prove which weights an arbitrary server has loaded. Server-advertised identity is evidence, not weight attestation. Use distinct output files and artifact identifiers for different quants.

The JSONL journal has an advisory single-writer lock. A torn final record is preserved in a recovery file before truncation; interior corruption fails closed. Final JSON summaries use atomic replacement. Authentication should use `SIXCAT_API_KEY` rather than putting a key in a saved command.

## Sampling and thinking

`--policy strict` uses temperature 0. `--policy vendor` resolves reviewed model-family settings from `sixcat/model-policies.json`; unknown families warn and fall back to strict. `--policy-family FAMILY` adopts a reviewed family for an unrecognized model alias. Inspect mappings with `python -m sixcat families --model MODEL`.

`--thinking on|off` is independent of sampling policy. Thinking-on raises task-shaped token budgets; `--budget CATEGORY=N` overrides a category explicitly. The probe records visible, hidden or unrevealed reasoning, without treating hidden thinking as a failure. Thinking-off rejects a visible reasoning leak. `--policy both` produces separate strict/vendor artifacts **sharing the invocation's time budget**, not two automatic 30-minute runs.

Custom sampling example:

```bash
python -m sixcat --model my-model --policy custom \
  --temperature 0.7 --top-p 0.95 --seed 1 --thinking on \
  --concurrency 4 --out results/custom.json
```

## Compare quants without rerunning the model

```bash
python -m sixcat compare results/q4.json results/q3.json --out results/q4-vs-q3.json
```

Compare validates policy, parser, benchmark content, selected keys, counts, completion state and code mode. It then reports exact pass-to-fail regressions and fail-to-pass improvements, plus a deterministic paired, category-stratified bootstrap interval. Use `--bootstrap-samples` and `--bootstrap-seed` to control the offline analysis. `--allow-mismatch` permits a descriptive delta, not a disguised statistical comparison.

At 20 items per category, one changed verdict moves that category by 5 points and the complete six-category overall by about 0.83 points. Bootstrap intervals describe resampling this **fixed challenge set**; they do not establish performance on all tasks or account for generation variability. A zero-width interval does not mean zero uncertainty.

## Quality and speed are separate measurements

All six categories retain completion, reasoning and answer token counts when supplied, request latency, provider timings, truncation and parse diagnostics. Missing provider telemetry stays missing.

`speed.request_weighted_tps` (legacy alias `suite_tps`) is tokens divided by summed request durations. It is **not** concurrent aggregate throughput. `execution.throughput_tps` uses tokens generated in the current session divided by the session's actual elapsed time, with explicit telemetry coverage. `execution_segments` preserves resumed sessions separately; cached responses are not counted as newly generated tokens.

## Optional tools: no longer default benchmark

These are opt-in and do not change the standard 120 questions:

```bash
# A deliberately requested seed series, still sharing one total 30-minute budget.
python -m sixcat repeat --seeds 1,2,3 --out-dir results/q4-repeats \
  --max-minutes 30 -- --model my-model --concurrency 4 --policy vendor

# Regrade the SAME saved first responses with the installed scorer; no model calls.
python -m sixcat rescore results/q4.json --out results/q4-rescored.json

# Export the saved coding completions for an optional external evaluator.
python -m sixcat export-evalplus results/q4.json --out results/q4-evalplus.jsonl
```

Repeats use fresh per-seed artifacts; endpoints may ignore seeds. Use matching seeds and settings on both models. Rescoring requires matching dataset identity and known first-response provenance; it never overwrites the input or invents attempt history for a legacy result.

EvalPlus export does **not** install or run EvalPlus and does not claim a HumanEval+ score. It emits `task_id`/`solution` records for the code items actually scored, preserving the 20-task subset. Use the [upstream EvalPlus evaluator](https://github.com/evalplus/evalplus) in a properly isolated environment and label any resulting subset metric separately from full HumanEval+.

### Full mode really is optional

`--full` selects **884 items**: 400 Knowledge, 100 Math, 100 Truth, 100 Instruct, 164 Code and 20 Tools. `--skip-code-exec` reduces full mode to 720. Full mode still has the time cap; only `--full --max-minutes 0` removes it. The separately bundled 541-row IFEval source is not an extra full-mode category.

## Hermes and stdio

The project-local [Hermes skill](.hermes/skills/sixcat-eval/SKILL.md) selects and verifies the target, previews settings, runs the raw provider model through an authenticated loopback proxy, and reads live receipts. It never starts, kills or replaces the actual model server. HTTP concurrency is supported through the proxy.

`--transport stdio` remains a serial request/response protocol, with real response deadlines and desynchronization protection. It requires `--concurrency 1`; use HTTP for parallel requests. See [the stdio protocol](docs/harness-stdio.md). A harness must not expose answer keys, add agent tools, or quietly substitute a different model; stdio is not automatically equivalent to independent raw-model evaluation.

## Code execution and safety

HumanEval runs code in a temporary guarded host subprocess: AST/import restrictions, an 8-second maximum further bounded by the invocation deadline, a randomized harness-owned success receipt, bounded stdout, and best-effort Unix CPU/memory/file-size limits. **This is not a security sandbox.** Use `--skip-code-exec` for untrusted generated code or run the whole benchmark in a separately isolated environment. Code-disabled results have a different comparison scope.

## Development and CI

```bash
python -m pip install -e . -r requirements-ci.txt
python -m pytest tests -q --timeout=90
python tools/validate_workflows.py
```

GitHub Actions tests Python 3.11–3.14 on Linux, plus Windows and macOS; executes a real loopback 120-item concurrent integration test; builds and checks wheels/sdists; and smoke-tests an installed wheel outside the checkout. CI requires at least 85% line coverage. Jobs have timeouts, read-only repository tokens, immutable action pins and non-persistent checkout credentials. Test reports, coverage, exact dependency versions, wheels and source archives are retained as artifacts. No live model key or GPU is required.

## Historical results, attribution, and license

[The original 0.5.1 README](README-v0.5.1.md), including its model results and self-evaluation caveats, is preserved unchanged. Do not compare those scores directly with parser-v5 results. [Release notes](RELEASE_NOTES.md) describe the migration.

The tiny datasets originate from [tinyBenchmarks](https://github.com/felipemaiapolo/tinyBenchmarks); IFEval constraints originate from [Google Research](https://github.com/google-research/google-research/tree/master/instruction_following_eval); HumanEval originates from [OpenAI](https://github.com/openai/human-eval). Frozen HumanEval challenge ordering retains the source attribution in `sixcat/selection.py`. SixCat's custom zero-shot subset scores are not official full-benchmark or IRT estimates. No claim of training-contamination immunity is made for public tasks.

MIT for the harness; upstream evaluation items retain their original licenses. Historical acknowledgments, evidence and measured results remain in the archived README and release notes.
