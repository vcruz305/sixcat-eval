# Sixcat 0.4.0 Release Notes

**Release date:** 2026-08-22

**Previous release:** 0.2.0

**Status:** final release

Sixcat 0.4.0 makes the short battery materially harder, fixes per-category scope,
and lets Hermes evaluate the raw model powering the current agent profile rather
than accidentally benchmarking the agent facade. It includes the unreleased 0.3.0
work; there is intentionally no separate v0.3.0 tag.

## Scoring and challenge integrity

- Limited runs use frozen `challenge-v1` selection. Quick starts with the hardest
  few tasks and Standard uses a hard/diverse subset instead of easy file prefixes.
- Knowledge, Math, and Truth difficulty comes from cross-model Sixcat receipts.
  Instruction uses a frozen constraint-density ranking over the shipped IFEval set.
- Code uses an independent 49-model HumanEval difficulty ranking. Quick begins with
  HumanEval/145, /132, and /130; Standard uses 20 hard tasks; Full executes all
  164 HumanEval tasks.
- Tools now grade exact arguments, call count/order, multi-call requests,
  distractors, and abstention. Historical first-tool-name-only grading is retired.
- Parser/grader identity advances to `v4`. Selection profile and fingerprint are
  persisted and enforced across resume and comparison boundaries.
- Full now contains 884 rows. Full mode preserves every shipped source row while
  Quick and Standard use challenge-first ordering.

## Correct run scope and sampling controls

- `--limit` is a per-category cap. Standard `--limit 20` targets approximately
  120 rows total; Knowledge splits those 20 slots across MMLU, ARC, HellaSwag,
  and WinoGrande instead of expanding to 80 rows.
- Result and journal identity records `limit_scope: per_category` so legacy
  per-dataset journals cannot resume silently under the corrected contract.
- `--policy custom` accepts exact temperature, top-p, top-k, min-p, and seed values.
- Thinking On/Off is a separate choice for every sampling mode. Thinking On is
  recommended for reasoning-capable endpoints and raises category token budgets.
  The pre-run probe still fails closed if the endpoint does not honor the choice.

## Hermes current-model evaluation

- `/sixcat-eval` asks first whether to evaluate the model powering the current
  Hermes session, another Hermes profile, or an alternate OpenAI-compatible endpoint.
- Current/profile mode resolves the profile's live model and provider and exposes a
  short-lived loopback proxy to the raw provider model. It does not score the Hermes
  agent facade, system prompt, memory, tools, or agent loop.
- The raw proxy pins model/provider identity, rejects silent fallback, never prints
  credentials, and closes in a `finally` block. The skill never kills, rebinds, or
  swaps a user's model server.
- Pre-run questions now carry distinct emoji, plain-language trade-offs, and a
  preview of endpoint, model identity, policy, seed, budgets, thinking, scope, and
  code-execution mode before launch.

## Compatibility and migration

- Parser-v2 and parser-v3 artifacts remain readable but are not directly comparable
  to parser-v4 challenge runs.
- Existing journals from before 0.4.0 require a new log or `--no-resume` when their
  parser, limit scope, selection fingerprint, or policy identity differs.
- `--full --max-minutes 0` is the explicit uncapped complete 884-row battery.
- HumanEval remains host-guarded by default. The guard is practical containment,
  not a security sandbox; use `--skip-code-exec` for actively malicious endpoints.

## Verification receipts

- `python -m pytest -q`: **210 passed, 164 subtests passed**.
- All **164/164** official HumanEval canonical solutions passed the guarded executor.
- Main CLI and the Hermes runner/preflight/status helpers compile.
- The final wheel contains `sixcat/selection.py`, model policy data, and all runtime
  datasets. Wheel and sdist publication hashes are attached to the GitHub Release.

---

# Sixcat 0.3.0 Release Notes

**Status:** included in 0.4.0; not tagged separately

## 0.3.0 highlights

- `--limit` is now a **per-category** cap. Standard `--limit 20` targets about
  120 scored rows, and Knowledge fairly splits its 20 slots across MMLU, ARC,
  HellaSwag, and WinoGrande instead of expanding to 80 rows.
- Run identity and final JSON now record `limit_scope: per_category`, preventing
  old per-dataset journals from being silently resumed under the new contract.
- `--policy custom` accepts explicit `--temperature` plus optional `--top-p`,
  `--top-k`, `--min-p`, `--thinking`, and `--seed` values.
- `/sixcat-eval` now uses emoji-labelled questions with plain-English summaries
  for target choice, sampling controls, seed, run size, and HumanEval safety.
- User-facing language calls reviewed mode **vendor-recommended
  temperature/settings**; unknown or stealth models recommend Custom sampling
  instead of presenting a strict fallback as a vendor recommendation.

---

# Sixcat 0.2.0 Release Notes

**Release date:** 2026-08-21
**Previous release:** 0.1.0
**Status:** final release

Sixcat 0.2.0 turns the original fixed, no-thinking smoke test into a policy-aware,
self-auditing local LLM battery. Runs now record the exact sampling policy,
measured token budgets, parser confidence, model-server identity, speed receipts,
and the full evidence needed to re-derive each score.

## Highlights

- Correct the score contract first: all 23 shipped IFEval constraints are explicit,
  empty/unknown constraints fail closed, and ARC labels map to presented choices.
- Keep HumanEval enabled without container overhead while blocking forged exits,
  dangerous imports, and candidate-controlled success.
- Emit scorer/parser `v3`; preserve archived v2 artifacts as readable but enforce a
  hard resume and comparison boundary across scorer versions.
- Preserve complete per-item evidence and self-auditing policy, parser, server,
  timeout, code-execution, token, confidence, and speed receipts.
- Reject mismatched fingerprints, sample scopes, timeouts, parser versions, and code
  modes unless a visibly non-comparable descriptive delta is explicitly requested.
- Run `strict`, reviewed `vendor`, or `both` policies from one CLI.
- Detect unsupported vendor names and fall back loudly to strict instead of guessing.
- Ship 29 cited model-family mappings, including current DeepSeek V4 Flash/Pro variants.
- Verify that the server honors the requested thinking mode before scoring begins.
- Use measured per-category token budgets and repeatable `--budget CATEGORY=N` overrides.
- Surface truncations, failed loops, low-confidence parses, and missing parser evidence.
- Record provider-independent wall TPS plus optional llama.cpp/SGLang prefill and decode TPS.
- Operate Sixcat conversationally from Hermes through the repo-local `/sixcat-eval` skill.

## Scorer v3 integrity corrections

- All 23 instruction IDs present in the shipped IFEval-100 subset now have explicit
  checkers. Unknown or malformed constraints and empty responses fail closed instead
  of receiving a pass.
- `less than` is strict `<`; bullet counts are exact; paragraph, postscript, section,
  JSON, two-response, capitalization, keyword, and letter rules follow the official
  IFEval contract.
- Kannada, Punjabi, Marathi, and Persian response requirements use deterministic
  `langdetect` validation. Generic English no longer passes a requested language.
- ARC gold answers resolve through each row's source `labels` array and are converted
  to the letter shown to the model. Numeric-label rows therefore score correctly.
- New runs and journals emit parser `v3`. Archived parser-v2 results remain readable,
  but parser mismatch is a hard resume/comparison boundary unless a descriptive
  `--allow-mismatch` comparison is explicitly requested.

## HumanEval host guard

HumanEval remains part of the default six-category battery without Docker or
container startup overhead. Candidate code runs in a fresh host Python process
with `-I -S`, a sanitized environment, a temporary working directory, and an
8-second timeout. Before execution, an AST gate rejects filesystem/process/network
escapes, dangerous process calls, top-level side effects, and private/dunder
traversal. The candidate namespace also gets an import allowlist and restricted
builtins. HumanEval's one official arithmetic-`eval` reference is handled by a
numeric-only evaluator rather than Python's general evaluator.

The grading harness catches `BaseException` around both candidate loading and the
official tests. After the checker returns, it emits a randomized harness-owned
success receipt; the parent requires both that receipt and exit code 0. Neither
`SystemExit(0)` nor a low-level `_exit(0)` can therefore forge a passing score.
All 164 shipped canonical solutions pass through this guarded path. Every result
records `code_execution: host-guarded`; `--skip-code-exec` records `disabled`,
omits Code from the mean, and adds `code-exec-disabled`.

This is a practical low-overhead guard, **not a security sandbox**. Users evaluating
an actively malicious or unknown endpoint should pass `--skip-code-exec`.

## Self-auditing result schema

New results identify themselves as structural schema `sixcat-v2` with scorer/parser
`v3`. Parser v3 distinguishes the corrected IFEval and ARC grading contract from
earlier local v2 artifacts. They include:

- model, endpoint, request timeout, and best-effort server properties;
- full resolved policy, source, fingerprint, probe details, and budgets;
- complete visible response and separate reasoning content;
- request parameters, finish reason, prompt/completion tokens, and parse confidence;
- deterministic grader provenance for IFEval, HumanEval, and structured tool calls;
- per-category token percentiles, truncation counts, loop failures, confidence counts,
  and speed statistics;
- labelled `overall[strict]` or `overall[vendor]` instead of a bare number;
- all item rows in the final JSON, not a lossy projection.

Result files are larger by design: a score is now accompanied by the evidence
needed to audit it.

## Comparison and reporting

`--policy both` runs strict then vendor with independent resources, journals, and
result files, followed by a vendor-minus-strict table.

Compare existing artifacts with:

```bash
python -m sixcat compare A.json B.json
```

A policy fingerprint mismatch is a hard error. Different parser/scorer versions,
limits, per-category sample counts, code-execution modes, or any timed-out run are
also hard run-scope mismatches.
`--allow-mismatch` permits only a loudly labelled descriptive delta. Parser
mismatch, policy-label mismatch, model mismatch, truncation, missing confidence,
and low-confidence parsing remain visible.

Unambiguous 0.1.0 result shapes can still be loaded read-only. They are labelled as
legacy v1 with an assumed strict policy and a distinct fingerprint; the source file
is never rewritten or presented as comparable to current parser-v3 strict.

## Policy-aware evaluation

### Three run modes

```bash
# Deterministic no-thinking baseline
python -m sixcat --model MODEL --policy strict

# Reviewed model-card settings
python -m sixcat --model MODEL --policy vendor

# Run strict then vendor with separate artifacts and a combined delta
python -m sixcat --model MODEL --policy both
```

`strict` remains the CLI default. It uses temperature 0 with thinking disabled.
`vendor` resolves the first verified model-name pattern in
`sixcat/model-policies.json`, defaults to seed 1, and carries its source citation
into every result. An unknown or unverified model emits a warning and resolves
to strict; it does not receive a guessed vendor recipe.

Specific patterns are ordered before generic families, and broad rows carry
validated `exclude_patterns` plus positive `required_patterns` where a base model
ID otherwise looks like chat. For example, `DeepSeek-V4-Flash-0731` and
`Qwen3.5` cannot be swallowed by generic rows, while unreviewed Base, Coder,
Embedding, Reranker, VL/Vision, Distill, and Speciale siblings fall back to strict.

### Immutable policy receipts

Every resolved policy includes:

- temperature, top-p, top-k, min-p, and thinking state;
- category token budgets;
- additional sampling fields such as seed and repetition/presence penalties;
- a cited source and reviewed date;
- a canonical 12-character SHA-256 policy fingerprint.

Policy values are defensively copied and frozen. Extra fields cannot override
protected request fields such as model, messages, tools, temperature, or thinking.

### Pre-run thinking probe

Before the first scored item, Sixcat asks the model a small arithmetic probe and
checks the returned `reasoning_content` or inline `<think>` trace:

- thinking policy + no reasoning evidence: abort;
- no-thinking policy + any reasoning evidence: abort;
- matching behavior: record the probe receipt and continue.

This prevents a server that ignores `enable_thinking` from silently producing a
score under the wrong policy.

## Measured token budgets

The old short limits silently converted `finish_reason=length` into wrong answers.
0.2.0 uses measured defaults and records every request's actual `max_tokens`.

| Category | Strict / no-think | Vendor / thinking |
|---|---:|---:|
| knowledge | 768 | 1597 |
| math | 1197 | 2048 |
| truth | 64 | 1892 |
| instruct | 1281 | 6767 |
| code | 1024 | 3072 |
| tools | 256 | 768 |

Override one or more categories without rewriting the global defaults:

```bash
python -m sixcat \
  --model MODEL \
  --policy vendor \
  --budget math=2304 \
  --budget code=4096
```

Unknown categories, malformed values, and non-positive budgets fail before a run.
The included `tools/calibrate_vendor_truth.py` utility performs a pinned,
self-auditing truth calibration and derives both a formula minimum and a
zero-truncation floor from uncensored completion-token receipts.

## Answer extraction and confidence receipts

The original v1 parsers often chose the last letter or number in a response. The
format-first answer extraction introduced in parser v2 remains part of scorer v3:

- recognizes explicit answer cues, boxed answers, bold choices, hash markers,
  affirmations, and lone-line choices before using a low-confidence fallback;
- strips inline `<think>...</think>` before answer extraction;
- never parses dedicated `reasoning_content` as the answer;
- normalizes thousands separators, leading zeros, and any trailing decimal zeros;
- records `high`, `low`, or `not_applicable` confidence per row.

The saved result partitions every row into high, low, not-applicable, or missing
confidence. Missing evidence and more than 20% low-confidence applicable parses
become visible overall flags. `tools/adjudicate_phase2.py` can replay the archived
v1 and v2 answer parsers over preserved raw completions and list every changed verdict.

## Reviewed vendor catalog

The catalog is a reviewed lookup, not automatic vendor-name guessing. One family
row can cover multiple sizes or quantized aliases through explicit patterns.
Every row has `verified: true`, an HTTPS source, and a reviewed date.

| Family | Temperature | top_p | top_k | min_p | Thinking | Source |
|---|---:|---:|---:|---:|:---:|---|
| `qwen3.8` | 1.0 | 0.95 | 20 | 0.0 | on | [official](https://huggingface.co/Qwen/Qwen3.8-27B) |
| `qwen3.6` | 1.0 | 0.95 | 20 | 0.0 | on | [official](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) |
| `qwen3.5` | 1.0 | 0.95 | 20 | 0.0 | on | [official](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) |
| `qwen3-next-thinking` | 0.6 | 0.95 | 20 | 0.0 | on | [official](https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Thinking) |
| `qwen3-next-instruct` | 0.7 | 0.8 | 20 | 0.0 | off | [official](https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct) |
| `qwen3` | 0.6 | 0.95 | 20 | 0.0 | on | [official](https://huggingface.co/Qwen/Qwen3-32B) |
| `qwen2.5` | 0.7 | 0.8 | 20 | n/a | off | [official](https://huggingface.co/Qwen/Qwen2.5-32B-Instruct/blob/main/generation_config.json) |
| `ornith-1.5-35b-a3b` | 0.6 | 0.95 | 20 | n/a | on | [official](https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B) |
| `llama-3` | 0.6 | 0.9 | n/a | n/a | off | [official](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct/blob/main/generation_config.json) |
| `deepseek-v4-flash-0731` | 1.0 | 0.95 | n/a | n/a | on | [official](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731) |
| `deepseek-v4-flash-vision` | 1.0 | 0.95 | n/a | n/a | on | [official](https://api-docs.deepseek.com/updates/#date-2026-08-21) |
| `deepseek-v4-flash-dspark` | 1.0 | 1.0 | n/a | n/a | on | [official](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-DSpark) |
| `deepseek-v4-flash` | 1.0 | 1.0 | n/a | n/a | on | [official](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash) |
| `deepseek-v4-pro-0813` | 1.0 | 0.95 | n/a | n/a | on | [official](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813) |
| `deepseek-v4-pro-dspark` | 1.0 | 1.0 | n/a | n/a | on | [official](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-DSpark) |
| `deepseek-v4-pro` | 1.0 | 1.0 | n/a | n/a | on | [official](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro) |
| `deepseek-v4` | 1.0 | 1.0 | n/a | n/a | on | [official](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro) |
| `deepseek-v3.2` | 1.0 | 0.95 | n/a | n/a | on | [official](https://huggingface.co/deepseek-ai/DeepSeek-V3.2) |
| `deepseek-r1` | 0.6 | 0.95 | n/a | n/a | on | [official](https://huggingface.co/deepseek-ai/DeepSeek-R1) |
| `glm-4.7` | 1.0 | 0.95 | n/a | n/a | on | [official](https://huggingface.co/zai-org/GLM-4.7) |
| `glm-4.6` | 1.0 | 0.95 | 40 | n/a | on | [official](https://huggingface.co/zai-org/GLM-4.6) |
| `kimi-k2-thinking` | 1.0 | n/a | n/a | n/a | on | [official](https://huggingface.co/moonshotai/Kimi-K2-Thinking) |
| `kimi-k2-instruct` | 0.6 | n/a | n/a | n/a | off | [official](https://huggingface.co/moonshotai/Kimi-K2-Instruct) |
| `gpt-oss` | 1.0 | 1.0 | n/a | n/a | on | [official](https://github.com/openai/gpt-oss) |
| `minimax-m2` | 1.0 | 0.95 | 40 | n/a | on | [official](https://huggingface.co/MiniMaxAI/MiniMax-M2.5) |
| `gemma-4` | 1.0 | 0.95 | 64 | n/a | on | [official](https://ai.google.dev/gemma/docs/core/model_card_4) |
| `magistral` | 0.7 | 0.95 | n/a | n/a | on | [official](https://huggingface.co/mistralai/Magistral-Small-2506) |
| `nemotron-3-ultra` | 1.0 | 0.95 | n/a | n/a | on | [official](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/modelcard) |
| `nemotron-3-nano` | 1.0 | 1.0 | n/a | n/a | on | [official](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16) |

### DeepSeek V4 distinctions

DeepSeek's three-month official inventory was reconciled against its Hugging Face
organization and API changelog:

- `DeepSeek-V4-Flash-0731` (2026-07-31): uses the official agentic point
  `temperature=1.0, top_p=0.95` because Sixcat includes a tools lane. Its plain
  generation config remains `top_p=1.0`.
- `DeepSeek-V4-Pro-0813` (2026-08-13): same reviewed agentic choice.
- `DeepSeek-V4-Flash-Vision-Exp` (2026-08-21): API-only experimental model;
  the official changelog supplies `temperature=1.0, top_p=0.95` for code-agent tests.
- `DeepSeek-V4-Flash-DSpark` and `DeepSeek-V4-Pro-DSpark`: their official cards
  say these are the same preview checkpoints with speculative modules attached,
  so they retain the parent `1.0 / 1.0` recipe.
- `dspark_*`, `dflash_*`, and `eagle3_*` helper repositories are draft modules,
  not standalone chat LLMs, and are intentionally not catalog families.

## Packaging

- Package version is `0.2.0`.
- `sixcat/model-policies.json` and all nine runtime JSONL datasets are included as package data.
- Runtime data now resolves from `sixcat/data/`, so an installed wheel can run without a source checkout.
- `MANIFEST.in` keeps release notes, calibration tools, and the project-local Hermes skill in the sdist.
- Build backend floor is `setuptools>=77`; license metadata uses the SPDX string `MIT`.
- Generated results, build artifacts, caches, and Unsloth compiled caches remain excluded from Git.
- Python 3.11+ remains the minimum version.
- `langdetect>=1.0.9,<2` provides deterministic IFEval response-language validation.

## Hermes project skill

The repository now ships `.hermes/skills/sixcat-eval/`, a project-local skill
compatible with current Hermes Agent project discovery.

```bash
cd sixcat-eval
hermes skills trust
hermes

# Then in the Hermes session:
/sixcat-eval
```

The skill:

1. probes common local endpoints without credentials, or one explicitly supplied
   authenticated `SIXCAT_BASE_URL`;
2. detects the exact target from `/v1/models` rather than confusing it with the
   cloud model running Hermes;
3. previews the cited policy, temperature, top-p/top-k/min-p, thinking, seed,
   budgets, and policy fingerprint;
4. asks for Vendor/Both/Strict and Standard/Quick/Full/Custom scope;
5. starts a tracked background process with fresh receipt paths;
6. summarizes live JSONL progress, truncations, loops, and confidence warnings;
7. rechecks model identity after the run and reports only from saved artifacts.

It does not start, stop, or swap model servers. It rejects ambiguous endpoints,
avoids concurrent runs by default, never silently resumes across server sessions,
and preserves partial journals when a user cancels.

Bundled helpers:

```bash
python .hermes/skills/sixcat-eval/scripts/preflight.py --json
python .hermes/skills/sixcat-eval/scripts/status.py --log RUN.jsonl --result RUN.json --json
```

Project skills are not auto-trusted after cloning. This is intentional Hermes
security behavior; trust is stored in the user's Hermes config, not in the repo.

## Speed receipts

Every request records wall time and provider-independent completion TPS:

```text
wall_tps = completion_tokens / request_wall_seconds
```

Category output includes mean item TPS and suite TPS. The final suite receipt
includes total completion tokens, total wall seconds, mean item TPS, and aggregate
suite TPS.

When present, Sixcat also preserves:

- llama.cpp `timings` as prefill/decode TPS;
- SGLang `meta_info` TTFT/TPOT-derived prefill/decode TPS.

The client also includes a tested TTFT calculation helper for future streaming
integration, but synchronous 0.2.0 runs do not claim that split.

## Loop-failure detection

A failed item is tagged as a loop when the same eight-word chunk appears at least
eight times in its reasoning or visible answer. Passed rows never count as loop
failures. Category tables and overall flags surface the count without treating a
long but non-repetitive answer as a loop.

## CLI additions

- `--policy strict|vendor|both`
- `--policy-file PATH`
- `--seed N`
- repeatable `--budget CATEGORY=N`
- `--request-timeout SECONDS`
- `--skip-code-exec`
- `sixcat compare A.json B.json [--allow-mismatch]`
- `SIXCAT_API_KEY` as the default credential source; when present, preflight requires
  exactly one explicit `--base-url` or `SIXCAT_BASE_URL` and never broadcasts it during discovery

## Breaking and migration notes

### Python API

`ChatClient` now requires a resolved `Policy` argument. Direct callers must use
`strict_policy()` or `resolve_policy()` before constructing the client.

### Result JSON

- `overall` changed from a bare number to `{ "policy": NAME, "score": VALUE }`.
- Current files require policy provenance, budgets, parser `v3`, per-category stats,
  explicit confidence buckets, and `overall_flags`.
- Archived parser-v2 files remain read-only compatible, but are non-comparable with v3.
- CLI JSONL journals begin with `_sixcat_run` identity metadata and score rows remain separate.
- Final results retain complete item receipts and are therefore larger.

### Operational behavior

- A failed thinking probe aborts before scoring.
- Unknown vendor models warn and run strict rather than receiving guessed settings.
- Resume requires an exact journal identity match across model, endpoint, policy fingerprint,
  parser, budgets, limit, request timeout, and code-execution mode; legacy or mismatched logs fail before model traffic.
- Comparing different fingerprints or run scopes fails unless `--allow-mismatch` is explicit.

## Verification receipts

Validated on 2026-08-21:

- `python -m pytest -q`: **189 passed, 163 subtests passed**.
- Main CLI and `sixcat compare` help both exit zero.
- Both Hermes helper scripts compile.
- Live preflight detected the single model on the active local endpoint and resolved
  its reviewed vendor source, exact settings, budgets, seed, and fingerprint.
- The status helper parsed a real JSONL journal, including truncation and confidence warnings,
  ignores only an unterminated active tail, and surfaces corrupt completed lines.
- `uvx --from build pyproject-build` built both
  `sixcat_eval-0.2.0.tar.gz` and `sixcat_eval-0.2.0-py3-none-any.whl` successfully.
- The isolated wheel matched current package sources byte-for-byte, carried all nine
  datasets plus the `langdetect` dependency metadata, passed all 164 canonical
  HumanEval solutions, and blocked low-level exit and dangerous-import probes.
- Its IFEval-100 probe found all 23 shipped IDs implemented, zero unsupported or
  empty-response passes, and zero generic-English passes for the four requested
  languages. ARC's nonstandard-label rows mapped to `C`, `B`, and `B` as presented.
- The extracted sdist matched all intended source/docs/tests/skill files byte-for-byte
  and passed the complete suite: **189 passed, 163 subtests passed**.

Repeat before publishing:

```bash
python -m pytest -q
uvx --from build pyproject-build
python -m sixcat --help
python -m sixcat compare --help
```

The built wheel must contain `sixcat/model-policies.json`. The project-local
Hermes skill is exercised separately through its preflight/status helpers because
it is a repository workflow, not Python wheel package data.

## Not in this release

- No automatic scraping of arbitrary model cards.
- No guessed policy for an unknown family.
- No automatic server launch, model swap, or process kill.
- No fabricated prefill/decode split.
- No claim that different policy fingerprints are directly comparable.
- No publication, tag, commit, or push until explicitly authorized.
