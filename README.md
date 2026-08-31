<img width="1774" height="887" alt="Sixcat Eval 0.2.0 dashboard with six category scores and terminal receipts" src="assets/sixcat-readme-header-v0.2.0.png" />

# sixcat-eval

Six community LLM categories. One overall number. Minutes, not hours.

**0.5.1 release:** `--transport stdio` lets a coding harness (ZCode, Claude
Code, Codex, …) answer Sixcat's raw requests directly when the model has no
exportable key — first validated end-to-end by a real 120-item run that
cross-validated the offline scorer item for item. HumanEval runs keep
prompt-provided helpers when the completion restates the entry def, and stdio
receipts are now retryable. See [RELEASE_NOTES.md](RELEASE_NOTES.md) and
[docs/harness-stdio.md](docs/harness-stdio.md).

**0.5.0 release:** thinking-on uses task-shaped safety ceilings instead of
the Qwen/Ornith p95 table (knowledge 8192, not 1597). The score sheet reports
`rtok`/`atok` when the engine splits them, and empty truncated think is a
fail. GLM-5.x vendor pre-closes think so Q2 GGUFs emit an answer. See
[RELEASE_NOTES.md](RELEASE_NOTES.md).

## Top features

- **Run the model behind your current Hermes agent.** The bundled `/sixcat-eval`
  skill asks whether to test the current session model, another Hermes profile, or
  an alternate endpoint. For Hermes profiles it bypasses the agent facade and
  evaluates the pinned raw provider model through a temporary authenticated
  loopback proxy that closes automatically.
- **A useful daily run with a 30-minute cap.** Six community categories roll into one
  unweighted overall; every completed item is journaled so interrupted runs resume instead
  of starting over.
- **Observe-only served context and ETA.** Preflight keeps every context candidate and
  its source, matches `/v1/models` to the requested ID, derives a safe input budget, and
  prints an ETA range from the thinking probe. It does not score, skip items, or set
  `--max-minutes`.
- **Scoring that fails closed.** Scorer/parser v4 explicitly checks all 23 shipped IFEval
  constraints, maps ARC labels to the choices shown to the model, ignores thinking as an
  answer, and never awards blank or unsupported instructions a free pass.
- **HumanEval by default, without Docker overhead.** Code runs in a short-lived guarded host
  subprocess with the official checker, an 8-second cap, and a harness-owned success receipt.
- **Reviewed model settings instead of guesses.** Run `strict`, cited `vendor`, or `both`
  across 30 reviewed model families; unknown models warn and fall back to strict.
- **Resume safely; compare without false equivalence.** Resume rejects changes in model,
  endpoint, policy fingerprint, parser, budgets, limit, request timeout, or code mode.
  Compare blocks policy/parser/scope/code-mode mismatches and timed-out runs unless an
  explicit override requests a descriptive-only delta.
- **Quality and speed receipts together.** Every artifact records truncation, loop failures,
  parse confidence, wall-clock tok/s, and provider prefill/decode rates when the server
  actually supplies them. Thinking-on also journals `rtok`/`atok` (API split only;
  `n/a` if omitted) and flags `trunc_in_think`. Works with `llama-server`, vLLM, Ollama, and other
  OpenAI-compatible servers.

Point it at any OpenAI-compatible server (`llama-server`, vLLM, Ollama), **or** drive completions from a coding harness over **stdio** (`--transport stdio`; see [docs/harness-stdio.md](docs/harness-stdio.md)). It prints:

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
6. **[Hermes workflow](#hermes-workflow)** — current-profile raw-model evaluation and live receipts.
7. **[Hermes question preview](#question-preview)** — every choice shown before a run starts.
8. **[Crash resume](#quick-start)** — live JSONL log + `--max-minutes`.
9. **[What we refuse to mix in](#what-we-refuse-to-mix-in)**

**Jump to:** [Top features](#top-features) · [Why](#why) · [Install](#quick-start) · [Hermes](#hermes-workflow) · [Question preview](#question-preview) · [Categories](#categories) · [Method](#method) · [0.4.1 notes](RELEASE_NOTES.md)

## Score contract

| Category | Source | Default n | Metric |
|---|---|---:|---|
| Knowledge | tinyMMLU + tinyARC + tinyHellaSwag + tinyWinogrande | 20 total | letter match |
| Math | tinyGSM8K | 20 | `####` number match |
| Truth | tinyTruthfulQA (mc1) | 20 | letter match |
| Instruct | IFEval | 20 | all listed constraints pass |
| Code | HumanEval | 20 | `pass@1` via host-guarded subprocess |
| Tools | 20 structured function-call challenges | 20 | exact calls, arguments, order, or abstention |

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
python -m sixcat preflight --base-url http://127.0.0.1:8085/v1 --model qwen38-27b
```

Default is `--limit 20` and `--max-minutes 30`. **The limit is per category**, so the standard run targets about 120 scored rows: 20 each for Knowledge, Math, Truth, Instruction, Code, and Tools. Knowledge's MMLU/ARC/HellaSwag/WinoGrande sources share those 20 slots instead of multiplying them to 80. Each item is appended to `run.jsonl` as it finishes. Every journal starts with a run-identity header covering model, endpoint, policy fingerprint, parser, budgets, limit, `limit_scope=per_category`, request timeout, and code-execution mode. Rerunning an identical command prints `SKIP` for completed keys; any identity mismatch aborts before model traffic. Pre-0.4 journals require a fresh log or `--no-resume`.

Before scoring, Sixcat records an observe-only **preflight** object: served context candidates (`/props` `n_ctx`, `/v1/models` `max_model_len` / `context_length`) matched to the requested model, a conservative advertised context, a safe input budget (advertised minus output reserve minus `max(512, 2%)`), and an ETA **range** from the existing thinking probe's actual usage/timings. `--ctx N` records an operator override as `configured`. Preflight never awards points and never sets `--max-minutes`. `python -m sixcat preflight` prints the context diagnostics without a generate; ETA appears on a scored run from the thinking probe.

Limited runs use frozen **`challenge-v1`** selection rather than the first rows:
Quick takes the hardest few, Standard takes a hard/diverse 20, and Full preserves
the complete source corpus. The selection profile and fingerprint are saved in
every journal/result, so old easy-prefix runs cannot resume or compare silently.

`--policy strict` is the deterministic temperature baseline: temperature 0; thinking defaults off but is an explicit independent `--thinking on|off` choice. `--policy vendor` is the internal CLI name for **vendor-recommended temperature/settings** from a reviewed model-card mapping, including seed 1 for easier repeat runs. Unknown names fall back to strict. `--policy custom` lets you supply exact settings such as `--temperature 0.7 --top-p 0.95`; temperature is required, while top-p/top-k/min-p/seed are optional. `--policy-family <family>` adopts a reviewed family's settings for an unmapped model ID (the receipt source says `adopted-for=<model>`). Thinking On is recommended for reasoning-capable endpoints and automatically raises token budgets. The pre-run probe auto-detects visible, hidden, or unrevealed thinking traces and still continues when thinking is on; it only fail-closes thinking-off if a visible reasoning trace leaks. In-flight scored items are controlled by `--concurrency N` (default 1; `llama-server -np` should be at least N) and are not part of journal identity.

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
If the cap hits first, do **not** start a clean `--no-resume` battery. Continue the
same `--log`/`--out` with `--retry remaining` (unscored items), `--retry failed`
(FAIL rows only), or `--retry incomplete` (both). The new rows merge into one result.

## Hermes workflow

The repository ships a project-local Hermes skill at
[`.hermes/skills/sixcat-eval/`](.hermes/skills/sixcat-eval/). It turns endpoint
selection, sampling policy, run scope, safety choices, live progress, and final
verification into one conversational `/sixcat-eval` workflow.

### Install and invoke

Current Hermes Agent versions discover project-local skills under `.hermes/skills/`.
After cloning, trust this repository once and start Hermes from the project root:

```bash
git clone https://github.com/vcruz305/sixcat-eval
cd sixcat-eval
python -m pip install -e .
hermes skills trust
hermes
```

Then invoke:

```text
/sixcat-eval
```

### What the skill does

1. **Asks for the target before probing anything.** It offers the exact model
   powering the current Hermes session, another Hermes profile, or an alternate
   OpenAI-compatible endpoint.
2. **Asks the remaining questions immediately, all with options.** Sampling,
   size, HumanEval execution, and thinking come next with no inspect/preflight
   delay. Custom follow-ups are preset rows, not a typed template.
3. **Shows the real identity.** Current/profile mode resolves the exact profile,
   provider, and model, including the current session's model override. Alternate
   endpoint mode verifies the selected model through `/v1/models`.
4. **Previews the complete policy.** Before execution it shows temperature,
   top-p/top-k/min-p, thinking state, seed, category budgets, cited source,
   selection profile, and policy fingerprint in plain English.
5. **Prints the exact run receipt.** Target, command, result path, JSONL journal,
   timeout, policy fingerprint, and code mode are restated without credentials.
6. **Runs in a tracked background process.** The skill reports category
   transitions, rows, pass/fail counts, truncations, loops, parse-confidence
   warnings, and saved receipt paths without flooding the chat per item.
7. **Verifies before reporting.** A zero exit code is not enough: the expected
   final JSON must exist, identity must remain pinned, and timeouts or incomplete
   evidence are labelled honestly.

### How current-profile evaluation works

Hermes' normal OpenAI-compatible API server is an **agent facade**. It adds the
profile's system prompt, tools, memory, and agent loop, and its `/v1/models` entry
can be a profile alias. That is useful for agent clients but is not a raw-model
benchmark.

For **Current Hermes session model** or **Another Hermes profile**, the bundled
`hermes_runner.py` instead:

- resolves the profile's existing provider authentication without printing it;
- pins the exact profile, provider, and model identity;
- starts a short-lived authenticated loopback proxy owned by the tracked run;
- forwards Sixcat requests directly to the raw provider model with the selected
  sampling parameters;
- rejects silent model/provider fallback after any request; and
- closes the proxy in `finally` on success, failure, timeout, or interruption.

It does **not** kill, swap, launch, or rebind the user's actual model server. For an
**Alternate OpenAI-compatible endpoint**, the skill uses the existing server's
`/v1/models` and `/v1/chat/completions` interfaces. Authenticated alternate
endpoints keep their credential in `SIXCAT_API_KEY`; the key is never placed in
commands, chat, journals, or final artifacts.

### Question preview

The skill asks the target question first:

> 🎯 **Do you want to run Sixcat against the model I am currently running,
> another Hermes profile, or an alternate OpenAI-compatible endpoint?**

- **🧠 Current Hermes session model (recommended)** — evaluate the exact raw model
  and provider powering the conversation, without the agent persona, tools,
  memory, or conversation.
- **👤 Another Hermes profile** — evaluate that profile's configured default model
  using its already-configured provider authentication.
- **🔌 Alternate OpenAI-compatible endpoint** — evaluate an already-running server
  selected through its `/v1/models` identity.

After the target answer, Hermes immediately presents these four questions
together. It does not inspect or preflight first. Every question uses selectable
options, including Custom follow-ups.

#### A. 🎛️ How should the model sample answers?

- **🏷️ Vendor-recommended temperature/settings (recommended)** — cited
  temperature and token filters, plus seed `1` where supported. Thinking is chosen
  separately.
- **🔬 Compare baseline vs vendor settings** — run deterministic and reviewed
  settings separately, then show a labelled delta.
- **🧊 Deterministic temperature baseline** — temperature `0`, no seed unless
  explicitly supplied.
- **🎛️ Custom sampling** — choose one preset row (0.7/none, 1.0/0.95, 0.6/0.95/20/0, or 0.0/none).

If preview later shows no reviewed vendor mapping, do not launch a fake
vendor run. Ask whether to adopt a listed vendor family, enter custom
sampling, or use the deterministic baseline.

#### B. 📏 How large should the evaluation be?

- **⚖️ Standard (recommended)** — 20 challenge-selected rows per category, about
  120 total, with a 30-minute safety cap.
- **⚡ Quick smoke** — 3 hard-first rows per category, about 18 total, with a
  10-minute cap. Useful for plumbing checks, not a final ranking.
- **🧭 Full battery** — all 884 shipped rows with no wall cap; this can exceed an
  hour and cost substantially more on hosted models.
- **🛠️ Custom size** — choose a preset: 5/15 min, 10/20 min, 40/60 min, or
  20 per category with no wall cap.

#### C. 🧪 Should Sixcat execute generated HumanEval code?

- **🛡️ Host-guarded HumanEval (recommended)** — run generated Python in a
  short-lived subprocess with isolated flags, a sanitized environment, temp
  directory, timeout, AST escape checks, restricted imports/builtins, and a
  harness-owned success receipt. This is **not a security sandbox**.
- **🚫 Skip generated-code execution** — Code becomes `n/a`, is omitted from the
  overall mean, and the receipt is flagged `code-exec-disabled`.

#### D. 🧠 Should reasoning/thinking be enabled?

- **🧠 Thinking on (recommended when supported)** — use the reasoning mode and
  larger category budgets. This remains the recommendation even when a cloud API
  hides thinking token blocks.
- **⚡ Thinking off** — faster, cheaper baseline. Do not pick this just because
  traces are hidden.

Thinking On is recommended unless the user chooses Off. The pre-run probe
auto-detects visible, hidden, or unrevealed traces and still continues when On
was selected. It only fail-closes Thinking Off if a visible reasoning trace leaks.

### What appears before execution

The final preview is designed to be sufficient even if the user never opened this
README. It includes:

```text
target kind:       Hermes runtime model / alternate endpoint
profile:           current or selected profile
model + provider:  exact pinned identities
sampling:          temperature, top-p, top-k, min-p, seed
thinking:          on/off + category token budgets
selection:         challenge-v1 + fingerprint
scope:             Quick / Standard / Full / Custom
code execution:    host-guarded / disabled
wall cap:          exact minutes
artifacts:         final JSON + live JSONL journal
```

New runs use fresh receipt paths and `--no-resume`. Resume is allowed only after
model, provider, endpoint, policy fingerprint, budgets, parser, selection
fingerprint, limit scope, timeout, code mode, and prior journal identity all match.
The skill never silently resumes across model-server sessions.

Project trust is stored in the user's Hermes configuration, not in this repository.
The complete operator contract is in
[`.hermes/skills/sixcat-eval/SKILL.md`](.hermes/skills/sixcat-eval/SKILL.md).

## Full vs smoke

| | Items | Typical wall on Quadro RTX 6000 @ ~24 tg |
|---|---:|---|
| default (`--limit 20`) | ~120 (20/category) | **≤30 min** |
| `--limit 3` | ~18 (3/category) | a few minutes |
| `--full` | 884 | can exceed 1 hour — not the daily run |

The comparison command refuses to compare a `--limit` smoke against a full run by default.

## Results

Complete battery runs. Partial and truncation-contaminated runs are omitted rather
than shown with asterisks.

**These two receipts are not directly comparable.** One is a live blind run against
a served endpoint with enforced budgets and real sampling; the other is a
self-administered offline replay with a disclosed-contaminated `tools` score. The
provenance columns matter more than the overall numbers.

| model | weights (HF) | precision | hardware / serving | transport | sixcat | policy | n | overall |
|---|---|---|---|---|---|---:|---:|---:|
| GLM-5.3-Flash | [`zai-org/GLM-5.3-Flash`](https://huggingface.co/zai-org/GLM-5.3-Flash) | vendor-hosted, unquantised | none — no model server | `stdio` | **v0.5.0** | vendor (`glm-5.x`) | 20 | 91.7 ⚠️ |
| Qwen3.8-27B EXL3 4.00bpw | [`turboderp/Qwen3.8-27B-exl3`](https://huggingface.co/turboderp/Qwen3.8-27B-exl3) @ `4.00bpw` | 4.00 bpw + Q4 KV cache | Quadro RTX 6000, 24 GB, Turing sm_75 · TabbyAPI | `openai` | **v0.5.1** | vendor (`qwen3.8`) | 10 | **75.0** |

Base model for the Qwen row: [`Qwen/Qwen3.8-27B`](https://huggingface.co/Qwen/Qwen3.8-27B)
(the `qwen3.8` vendor policy cites that model card, reviewed 2026-08-20).
Receipts were produced on different sixcat versions — v0.5.0 for GLM, v0.5.1 for
Qwen — which is a further reason not to read the two overall scores against each
other.

| model | knowledge | math | truth | instruct | code | tools |
|---|---:|---:|---:|---:|---:|---:|
| GLM-5.3-Flash | 60.0 | 100.0 | 95.0 | 95.0 | 100.0 ⚠️ | 100.0 ⚠️ |
| Qwen3.8-27B EXL3 4.00bpw | 40.0 | **100.0** | 60.0 | **90.0** | 80.0 | **80.0** |

Bold = zero loop failures, zero truncation, zero empty answers.

### GLM-5.3-Flash — 91.7 ⚠️ read the caveats

Full receipt: [`SELF_EVAL_REPORT.md`](SELF_EVAL_REPORT.md). The session model could
not be reached over HTTP (client-gated provider gateway; the stored key had no
balance for this model), so it was scored by offline replay and reproduced over
`--transport stdio`. Its own Section 4 discloses:

- **Self-administered.** The model producing the answers and the agent running the
  harness are the same system. No independent sampler and no temperature-1.0 draw —
  each answer is a single deliberate response.
- **`tools` 100.0 is contaminated.** The model saw `sixcat/tools.py`, whose `ITEMS`
  constants contain the expected calls inline. Treat as an upper bound, not evidence.
- **`code` 100.0 carries a known-harness format fix.** HumanEval/32 was completed
  with the harness's "repeated entry function" heuristic in mind; the report states a
  live model would likely fail that item.
- **No token budgets enforced**, so truncation dynamics at the budget edge were never
  exercised — the failure mode that dominates real local-model runs.
- No speed or usage telemetry: this receipt measures quality only.

### Qwen3.8-27B EXL3 4.00bpw — 75.0

Live blind run over an OpenAI-compatible endpoint. Quadro RTX 6000 (Turing sm_75,
24 GB) running TabbyAPI on a Turing-patched ExLlamaV3, Q4 KV cache, 262,144-token
context, `--concurrency 4`, budgets enforced. 28.7 tok/s decode, ~457 tok/s prefill
at 32K. 60/60 items scored, no timeout.

`math`, `instruct` and `tools` recorded zero loops, zero truncation and zero empty
answers. `knowledge`, `truth` and `code` carried `trunc-in-think` and loop failures,
so those three are weaker evidence than their scores suggest.

### Sampling policy matters more than expected on local models

Same model, same hardware, same harness — only `--policy` changed:

| policy | sampling | knowledge | math | truth | instruct | code | tools | overall |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `strict` | temp 0.0 | 50.0 | 100.0 | 50.0 | 80.0 | 0.0 *(n=2)* | *not reached* | 56.0 |
| `vendor` | temp 1.0, top_p 0.95, top_k 20 | 40.0 | 100.0 | 60.0 | 90.0 | 80.0 | 80.0 | **75.0** |

Greedy decoding pushed this long-thinking model into repetition loops. The loops
consumed the time budget, the run hit `--max-minutes`, and because categories are
processed in order the tail went unscored — `tools` came back `n=0` in five of six
timed-out runs while `knowledge` and `math` were always complete. Read as model
quality that looks like a badly degraded quantisation. It was the sampling config.

Two practical notes for local-model evaluation:

- A model served under a non-descriptive id (`4.00bpw`, `local-model`) matches no
  pattern in `model-policies.json`, so `--policy vendor` will not resolve on its own.
  Pass `--policy-family` explicitly, or serve it under a matching name.
- `--concurrency` is what lets a slow local model finish inside the time budget.
  Against a batching server it roughly doubled aggregate throughput here, turning a
  run that had timed out six times into a complete one.

Check the diagnostic columns before reading any score as quality: `ctok_max` at the
category budget means truncation, `empty > 0` means a parser or format mismatch, and
a whole category coming back unparseable usually means server configuration rather
than the model.

## Method

- One stream. One model id. Same prompt template every run.
- Multiple choice: “Reply with only the letter.” Scorer/parser v4 keeps the format-first
  extraction introduced in v2, records fallback confidence, and maps ARC source labels to
  the displayed choice letters.
- GSM8K: “End with `#### <number>`.” Scorer/parser v4 prefers `####`, boxed, or explicit
  final answers before its low-confidence fallback.
- Dedicated or inline thinking is never parsed as the answer.
- Tools: OpenAI `tools=` on `/v1/chat/completions`.
- Context and probe-cost estimates are preflight inputs with provenance, not scores.

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
