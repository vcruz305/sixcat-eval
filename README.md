<img width="1774" height="887" alt="image" src="https://github.com/user-attachments/assets/78f2fd46-8669-4176-9282-635f83582c6d" />

# sixcat-eval

Six community LLM categories. One overall number. Minutes, not hours.

**0.2.0 release candidate:** see [RELEASE_NOTES.md](RELEASE_NOTES.md) for policy modes,
all 29 reviewed model families, scorer/parser v3, speed receipts, comparison, and migration notes.

Point it at any OpenAI-compatible server (`llama-server`, vLLM, Ollama). It prints:

```text
model: example-model
url:   http://127.0.0.1:8085/v1
policy: vendor (abc123def456)
code execution: host-guarded

category        score     n  trunc  loops  high   low   n/a  miss      pp      tg     tps
-----------------------------------------------------------------------------------------
knowledge       62.5    12      0      0    12     0     0     0     n/a     n/a     n/a
math            33.3     3      0      0     3     0     0     0     n/a     n/a     n/a
truth           66.7     3      0      0     3     0     0     0     n/a     n/a     n/a
instruct        33.3     3      0      0     0     0     3     0     n/a     n/a     n/a
code             0.0     3      0      0     0     0     3     0     n/a     n/a     n/a
tools           66.7     3      0      0     0     0     3     0     n/a     n/a     n/a
-----------------------------------------------------------------------------------------
overall[vendor]       43.8
```

**Overall is the unweighted mean of the category scores that actually ran.** Each category is `100 * n_correct / n`. Empty category → omitted from the mean, not a zero.

Failed items can also be tagged as **loops**: the same 8-word chunk appears 8+ times in the thinking/answer text. Each category reports `loop_failures` (count of *failed* loop items). Passes never count, even if the trace repeats. The printed table has a `loops` column; the JSON has `stats.<cat>.loop_failures` and per-row `loop`. Topline flag: `loop-failures:truth`.

Each item records `wall_s` and `wall_tps` from client wall-clock (`completion_tokens / request seconds`). That works on any OpenAI-compatible server. Category stats add `tps_mean` (average of per-item rates) and `suite_tps` (`sum(ctok) / sum(wall_s)`). The battery JSON has `speed` with the same fields across all six categories. The table `tps` column is per-category mean; the footer is suite `suite_tps` and overall mean.

When the server also sends llama.cpp `timings` or SGLang `meta_info`, rows keep `prefill_tps` / `decode_tps` as extras (`pp` / `tg`). Missing provider split stays `n/a`. sixcat will not invent that split from a single wall-clock number.

This is **not** a replacement for the full Open LLM Leaderboard, MixEval-Hard, or SWE-bench. It is the daily driver you can finish on a 24 GB card before lunch.

## Why

I ship GGUF packs and need a number I can trust the same afternoon, on the same card that will run the file.

Full MMLU, MATH, LiveCodeBench, and MixEval-Hard are the right *subjects*. They are the wrong *wall clock* on a Quadro RTX 6000 at ~24 tok/s. A 740-item “complete” pass blew past an hour here. That is useless for comparing Q4 vs Q3 vs a challenger before you upload.

So this tool takes the suites people already quote — tinyBenchmarks anchors, IFEval, HumanEval, a small tool-call set — and scores them as six categories plus one unweighted overall. Default cap is 30 minutes. Each item is flushed to a JSONL log so a crash or a killed job can resume instead of starting over.

If you want the academic 740, pass `--full --max-minutes 0`. That is opt-in. The default is the run you can actually finish.

## What's in here

1. **[Why](#why)** — 30 minutes, six community subjects, one overall.
2. **[Score contract](#score-contract)** — six buckets, one average.
3. **[Categories](#categories)** — what each number is.
4. **[Quick start](#quick-start)** — one command against `:8085`.
5. **[Hermes workflow](#hermes-workflow)** — conversational detection, policy preview, and live status.
6. **[Crash resume](#quick-start)** — live JSONL log + `--max-minutes`.
7. **[What we refuse to mix in](#what-we-refuse-to-mix-in)**

**Jump to:** [Why](#why) · [Install](#quick-start) · [Hermes](#hermes-workflow) · [Categories](#categories) · [Method](#method) · [0.2.0 notes](RELEASE_NOTES.md)

## Score contract

| Category | Source | Default n | Metric |
|---|---|---:|---|
| Knowledge | tinyMMLU + tinyARC + tinyHellaSwag + tinyWinogrande | 80 (20×4) | letter match |
| Math | tinyGSM8K | 20 | `####` number match |
| Truth | tinyTruthfulQA (mc1) | 20 | letter match |
| Instruct | IFEval | 20 | all listed constraints pass |
| Code | HumanEval | 20 | `pass@1` via host-guarded subprocess |
| Tools | 20 scripted function-call items | 20 | correct tool name (or none) |

tiny* sets are the 100-item IRT anchors from [tinyBenchmarks](https://github.com/felipemaiapolo/tinyBenchmarks) / [HF](https://huggingface.co/tinyBenchmarks). IFEval IDs follow [google-research/instruction_following_eval](https://github.com/google-research/google-research/tree/master/instruction_following_eval). HumanEval is the OpenAI set.

## Categories

**Knowledge** — four multiple-choice suites the Open LLM Leaderboard made standard. We do **not** feed the few-shot `input_formatted` blobs; zero-shot letter only.

**Math** — grade-school word problems. Parser prefers `#### N`, boxed values, or explicit final-answer cues, then labels any last-number fallback as low confidence.

**Truth** — TruthfulQA mc1 (best true vs common myths).

**Instruct** — all 23 constraint IDs present in the shipped IFEval-100 subset have
explicit local checkers. Unknown or malformed IDs fail closed. Response-language
constraints use deterministic `langdetect` checks rather than treating any text as a pass.

**Code** — HumanEval `pass@1`. Completions run in a temp process with an 8s cap. First 20 tasks only.

**Tools** — twenty prompts with a five-tool schema (`list_dir`, `read_file`, `search`, `add`, `write_file`). Two items require **no** tool. This is not Hermes loop-gate; for the 20-task agent harness use [hermes-agentic-bench](https://github.com/vcruz305/hermes-agentic-bench).

## Quick start

Python 3.11+. Installing the project also installs its small `langdetect` dependency.

```bash
git clone https://github.com/vcruz305/sixcat-eval
cd sixcat-eval
python -m pip install -e .

python -m sixcat --base-url http://127.0.0.1:8085/v1 --model qwen38-27b --out run.json
```

Default is `--limit 20` and `--max-minutes 30`. Each item is appended to `run.jsonl` as it finishes. Every 0.2 CLI journal starts with a run-identity header covering model, endpoint, policy fingerprint, parser, budgets, limit, request timeout, and code-execution mode. Rerunning an identical command prints `SKIP` for completed keys; any identity mismatch aborts before model traffic. Pre-0.2 journals require a fresh log or `--no-resume`.

`--policy strict` is greedy, thinking off. `--policy vendor` uses the reviewed per-model sampling, thinking budgets, and seed 1 (first matching `verified` family in `sixcat/model-policies.json`). Unknown names fall back to strict. Do not pass `--seed` unless you want to override that receipt.

For authenticated endpoints, set `SIXCAT_API_KEY`; the CLI reads it without putting the key in your saved command. An explicit `--api-key` still overrides the environment.

HumanEval runs by default in a short-lived **host-guarded subprocess**: isolated Python flags, sanitized environment, temporary working directory, timeout, an import allowlist, restricted candidate builtins, and an AST gate that rejects filesystem/process/network escapes and private/dunder traversal. The parent records a pass only after the official checker returns and the harness emits its randomized success receipt; a low-level exit code alone cannot pass. The one official arithmetic-`eval` task uses a numeric-only evaluator. This is deliberately lower overhead than a container, but it is **not a security sandbox**. Use `--skip-code-exec` if the served model is untrusted.

Use `--policy both` for separate strict/vendor artifacts and a vendor-minus-strict table. Compare completed files with `python -m sixcat compare A.json B.json`. Different policy fingerprints, limits, category counts, or timed-out runs fail comparison unless `--allow-mismatch` explicitly requests a descriptive-only delta.

```text
PASS knowledge/mmlu:3 pred=B gold=B
FAIL math/gsm:1 pred=12 gold=29
TIMEUP before instruct/ifeval:1005
```

`--full` is 740 items. It still stops at 30 minutes unless you pass `--max-minutes 0`.

## Hermes workflow

Current Hermes Agent versions discover project-local skills under `.hermes/skills/`.
After cloning, trust this repository once, then invoke the conversational operator:

```bash
cd sixcat-eval
hermes skills trust
hermes
```

```text
/sixcat-eval
```

Hermes probes `/v1/models`, shows the exact detected model and reviewed temperature/policy,
asks for Vendor/Both/Strict and Standard/Quick/Full/Custom scope, starts a tracked background
run, and reports live JSONL status plus final self-auditing receipts. It never starts, stops,
or swaps the model server. Project trust is stored in the user's Hermes config, not this repo.

## Full vs smoke

| | Items | Typical wall on Quadro RTX 6000 @ ~24 tg |
|---|---:|---|
| default (`--limit 20`) | ~180 | **≤30 min** |
| `--limit 3` | 27 | a few minutes |
| `--full` | 740 | can exceed 1 hour — not the daily run |

The comparison command refuses to compare a `--limit` smoke against a full run by default.

## Method

- One stream. One model id. Same prompt template every run.
- Multiple choice: “Reply with only the letter.” Parser v2 prefers explicit answer formats and records fallback confidence.
- GSM8K: “End with `#### <number>`.” Parser v2 prefers `####`, boxed, or explicit final answers before its low-confidence fallback.
- Dedicated or inline thinking is never parsed as the answer.
- Tools: OpenAI `tools=` on `/v1/chat/completions`.

Unit tests (no GPU):

```bash
python -m pytest -q
```

## What we refuse to mix in

- `llama-bench` tok/s (speed, not quality)
- Hosted API queue time
- ngram / cache-hit decode
- Hermes `-Q` 0-tool scores
- Ada / Blackwell numbers labeled as this box

## License

MIT for the harness. Upstream eval items keep their original licenses (tinyBenchmarks, IFEval, HumanEval).
