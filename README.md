<img width="1774" height="887" alt="Sixcat Eval 0.2.0 dashboard with six category scores and terminal receipts" src="assets/sixcat-readme-header-v0.2.0.png" />

# sixcat-eval

Six community LLM categories. One overall number. Minutes, not hours.

**0.4.0 release:** see [RELEASE_NOTES.md](RELEASE_NOTES.md) for policy modes,
all 29 reviewed model families, scorer/parser v4, speed receipts, comparison, and migration notes.

## Top features

- **A useful daily run with a 30-minute cap.** Six community categories roll into one
  unweighted overall; every completed item is journaled so interrupted runs resume instead
  of starting over.
- **Scoring that fails closed.** Scorer/parser v4 explicitly checks all 23 shipped IFEval
  constraints, maps ARC labels to the choices shown to the model, ignores thinking as an
  answer, and never awards blank or unsupported instructions a free pass.
- **HumanEval by default, without Docker overhead.** Code runs in a short-lived guarded host
  subprocess with the official checker, an 8-second cap, and a harness-owned success receipt.
- **Reviewed model settings instead of guesses.** Run `strict`, cited `vendor`, or `both`
  across 29 reviewed model families; unknown models warn and fall back to strict.
- **Resume safely; compare without false equivalence.** Resume rejects changes in model,
  endpoint, policy fingerprint, parser, budgets, limit, request timeout, or code mode.
  Compare blocks policy/parser/scope/code-mode mismatches and timed-out runs unless an
  explicit override requests a descriptive-only delta.
- **Quality and speed receipts together.** Every artifact records truncation, loop failures,
  parse confidence, wall-clock tok/s, and provider prefill/decode rates when the server
  actually supplies them. Works with `llama-server`, vLLM, Ollama, and other
  OpenAI-compatible servers.

Point it at any OpenAI-compatible server (`llama-server`, vLLM, Ollama). It prints:

```text
model: example-model
url:   http://127.0.0.1:8085/v1
policy: vendor (abc123def456)
source: illustrative README fixture
code execution: host-guarded

category        score     n  trunc  loops  high   low   n/a  miss      pp      tg     tps
-----------------------------------------------------------------------------------------
knowledge       75.0    12      0      0     9     3     0     0  1260.4    43.8    38.6
math            83.3     6      0      0     5     1     0     0  1184.7    40.9    35.2
truth           60.0     5      0      0     4     1     0     0  1218.5    42.3    36.8
instruct        87.5     8      0      0     0     0     8     0  1096.2    39.6    34.1
code            50.0     6      0      0     0     0     6     0   967.8    36.4    31.7
tools          100.0     4      0      0     0     0     4     0  1315.9    45.1    40.6
-----------------------------------------------------------------------------------------
overall[vendor]       76.0
speed: 2184 ctok / 60.0s  suite_tps 36.4  mean 36.2
```

**Overall is the unweighted mean of the category scores that actually ran.** Each category is `100 * n_correct / n`. Empty category → omitted from the mean, not a zero.

Failed items can also be tagged as **loops**: the same 8-word chunk appears 8+ times in the thinking/answer text. Each category reports `loop_failures` (count of *failed* loop items). Passes never count, even if the trace repeats. The printed table has a `loops` column; the JSON has `stats.<cat>.loop_failures` and per-row `loop`. Topline flag: `loop-failures:truth`.

Each item records `wall_s` and `wall_tps` from client wall-clock (`completion_tokens / request seconds`). That works on any OpenAI-compatible server. Category stats add `tps_mean` (average of per-item rates) and `suite_tps` (`sum(ctok) / sum(wall_s)`). The battery JSON has `speed` with the same fields across all six categories. The table `tps` column is per-category mean; the footer is suite `suite_tps` and overall mean.

When the server also sends llama.cpp `timings` or SGLang `meta_info`, rows keep `prefill_tps` / `decode_tps` as extras (`pp` / `tg`). Missing provider split stays `n/a`. sixcat will not invent that split from a single wall-clock number.

This is **not** a replacement for the full Open LLM Leaderboard, MixEval-Hard, or SWE-bench. It is the daily driver you can finish on a 24 GB card before lunch.

## Why

I ship GGUF packs and need a number I can trust the same afternoon, on the same card that will run the file.

Full MMLU, MATH, LiveCodeBench, and MixEval-Hard are the right *subjects*. They are the wrong *wall clock* on a Quadro RTX 6000 at ~24 tok/s. An 884-item complete pass can blow past an hour here. That is useless for comparing Q4 vs Q3 vs a challenger before you upload.

So this tool takes the suites people already quote — tinyBenchmarks anchors, IFEval, HumanEval, a small tool-call set — and scores them as six categories plus one unweighted overall. Default cap is 30 minutes. Each item is flushed to a JSONL log so a crash or a killed job can resume instead of starting over.

If you want all 884 shipped rows, pass `--full --max-minutes 0`. That is opt-in. The default is the run you can actually finish.

## What's in here

1. **[Top features](#top-features)** — the value and safety contract at a glance.
2. **[Why](#why)** — 30 minutes, six community subjects, one overall.
3. **[Score contract](#score-contract)** — six buckets, one average.
4. **[Categories](#categories)** — what each number is.
5. **[Quick start](#quick-start)** — one command against `:8085`.
6. **[Hermes workflow](#hermes-workflow)** — conversational detection, policy preview, and live status.
7. **[Crash resume](#quick-start)** — live JSONL log + `--max-minutes`.
8. **[What we refuse to mix in](#what-we-refuse-to-mix-in)**

**Jump to:** [Top features](#top-features) · [Why](#why) · [Install](#quick-start) · [Hermes](#hermes-workflow) · [Categories](#categories) · [Method](#method) · [0.2.0 notes](RELEASE_NOTES.md)

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

**Code** — HumanEval `pass@1`. Quick/Standard use a frozen externally ranked
hard-task order; Full runs all 164 tasks. Completions run in a temp process with an 8s cap.

**Tools** — twenty challenge prompts with a five-tool schema (`list_dir`, `read_file`, `search`, `add`, `write_file`). Grading now checks exact arguments, call count/order, multi-call requests, distractors, and abstention—not just the first tool name. This is not Hermes loop-gate; for the 20-task agent harness use [hermes-agentic-bench](https://github.com/vcruz305/hermes-agentic-bench).

## Quick start

Python 3.11+. Installing the project also installs its small `langdetect` dependency.

```bash
git clone https://github.com/vcruz305/sixcat-eval
cd sixcat-eval
python -m pip install -e .

python -m sixcat --base-url http://127.0.0.1:8085/v1 --model qwen38-27b --out run.json
```

Default is `--limit 20` and `--max-minutes 30`. **The limit is per category**, so the standard run targets about 120 scored rows: 20 each for Knowledge, Math, Truth, Instruction, Code, and Tools. Knowledge's MMLU/ARC/HellaSwag/WinoGrande sources share those 20 slots instead of multiplying them to 80. Each item is appended to `run.jsonl` as it finishes. Every journal starts with a run-identity header covering model, endpoint, policy fingerprint, parser, budgets, limit, `limit_scope=per_category`, request timeout, and code-execution mode. Rerunning an identical command prints `SKIP` for completed keys; any identity mismatch aborts before model traffic. Pre-0.4 journals require a fresh log or `--no-resume`.

Limited runs use frozen **`challenge-v1`** selection rather than the first rows:
Quick takes the hardest few, Standard takes a hard/diverse 20, and Full preserves
the complete source corpus. The selection profile and fingerprint are saved in
every journal/result, so old easy-prefix runs cannot resume or compare silently.

`--policy strict` is the deterministic temperature baseline: temperature 0; thinking defaults off but is an explicit independent `--thinking on|off` choice. `--policy vendor` is the internal CLI name for **vendor-recommended temperature/settings** from a reviewed model-card mapping, including seed 1 for easier repeat runs. Unknown names fall back to strict. `--policy custom` lets you supply exact settings such as `--temperature 0.7 --top-p 0.95`; temperature is required, while top-p/top-k/min-p/seed are optional. Thinking On is recommended for reasoning-capable endpoints and automatically raises token budgets; the pre-run probe fails closed if the endpoint cannot expose the requested trace.

```bash
python -m sixcat --base-url http://127.0.0.1:8085/v1 --model unknown-model \
  --policy custom --temperature 0.7 --top-p 0.95 --thinking off --limit 20
```

For authenticated endpoints, set `SIXCAT_API_KEY`; the CLI reads it without putting the key in your saved command. An explicit `--api-key` still overrides the environment.

HumanEval runs by default in a short-lived **host-guarded subprocess**: isolated Python flags, sanitized environment, temporary working directory, timeout, an import allowlist, restricted candidate builtins, and an AST gate that rejects filesystem/process/network escapes and private/dunder traversal. The parent records a pass only after the official checker returns and the harness emits its randomized success receipt; a low-level exit code alone cannot pass. The one official arithmetic-`eval` task uses a numeric-only evaluator. This is deliberately lower overhead than a container, but it is **not a security sandbox**. Use `--skip-code-exec` if the served model is untrusted.

Use `--policy both` for separate strict/vendor artifacts and a vendor-minus-strict table. Compare completed files with `python -m sixcat compare A.json B.json`. Different policy fingerprints, limits, category counts, or timed-out runs fail comparison unless `--allow-mismatch` explicitly requests a descriptive-only delta.

```text
PASS knowledge/mmlu:3 pred=B gold=B
FAIL math/gsm:1 pred=12 gold=29
TIMEUP before instruct/ifeval:1005
```

`--full` is 884 items. It still stops at 30 minutes unless you pass `--max-minutes 0`.

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

`/sixcat-eval` asks for the target **before probing anything**. The recommended
choice is the exact model backing the current Hermes session; you can instead choose another
Hermes profile or an alternate OpenAI-compatible endpoint.

For the current-session/profile choices, Sixcat does **not** benchmark Hermes' normal API-server
agent facade (which adds profile instructions, tools, memory, and an agent loop). It resolves that
profile's provider authentication, pins the exact model/provider, and creates a temporary
authenticated loopback proxy that calls the raw model with the reviewed Sixcat sampling policy.
The proxy is owned by the tracked run and closes automatically. Alternate endpoints still use
`/v1/models` discovery.

Hermes then shows the exact target and explains temperature, token filters, thinking, and seed in
plain English. Its emoji-labelled questions offer vendor-recommended temperature/settings when a
reviewed mapping exists, or custom sampling first for unknown/stealth models. It then asks for
Standard/Quick/Full/Custom size, explains host-guarded HumanEval, and separately asks whether
thinking should be On or Off before starting a tracked run.
The run reports live JSONL status plus final self-auditing receipts. It never starts, stops, or swaps the
actual model server. Project trust is stored in the user's Hermes config, not this repo.

## Full vs smoke

| | Items | Typical wall on Quadro RTX 6000 @ ~24 tg |
|---|---:|---|
| default (`--limit 20`) | ~120 (20/category) | **≤30 min** |
| `--limit 3` | ~18 (3/category) | a few minutes |
| `--full` | 884 | can exceed 1 hour — not the daily run |

The comparison command refuses to compare a `--limit` smoke against a full run by default.

## Method

- One stream. One model id. Same prompt template every run.
- Multiple choice: “Reply with only the letter.” Scorer/parser v4 keeps the format-first
  extraction introduced in v2, records fallback confidence, and maps ARC source labels to
  the displayed choice letters.
- GSM8K: “End with `#### <number>`.” Scorer/parser v4 prefers `####`, boxed, or explicit
  final answers before its low-confidence fallback.
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
