# Eval-run findings and harness review — 2026-08-28

Companion to [SELF_EVAL_REPORT.md](../SELF_EVAL_REPORT.md) (the self-administered
GLM-5.3-Flash battery run, overall 91.7). This document records what a full
review of the harness, docs, Hermes skill, and shipped data found afterwards,
what was patched in this repository, and what was deliberately left alone.

## 1. Upstream data quirks — verified, NOT patched (deliberate)

Three items in the default battery behaved badly during the run. Before
patching, each was checked against its upstream source. All three turn out to
be **faithful mirrors of upstream anchor data**, so editing them would break
comparability with tinyBenchmarks/IFEval numbers — the entire reason those
anchors were chosen. They are documented here instead.

| item | symptom | upstream verdict |
|---|---|---|
| `ifeval_100` key `1174` (weather-bot template) | prompt says "The letter o should appear **at least** 6 times" but the grader kwargs say `let_relation: "less than"` — no response can pass | the contradiction exists in **google/IFEval itself** (verified against `google/IFEval` on Hugging Face: same prompt, same `less than` kwargs) |
| `tiny_truthfulqa` "Bill Gates" last-name item | key is "Haslam." while "Gates." sits one slot over | **tinyBenchmarks/tinyTruthfulQA labels "Haslam." correct** (mc1 labels `[1,0,0,0]`, mc2 agrees) — an adversarial item with a surprising key, not a keying bug |
| `tiny_mmlu` index 8, "Cultural homogenization." | two-word stem; choices are statement-number combos ("1,2,3") whose statements never appear | **known malformed MMLU item** (business_ethics), present in tinyBenchmarks/tinyMMLU verbatim and cited in benchmark-noise literature (arXiv:2607.23915) |

Consequence for receipts: up to 3 of the 120 default items are effectively
noise inherited from upstream (a guaranteed IFEval fail, a TruthfulQA item
whose key contradicts the intuitive read, and an MMLU guessing item). If sixcat
ever wants a "clean" variant, that should be a **new selection profile**
(e.g. `challenge-v2-clean`) rather than an in-place edit, so old receipts stay
resumable and comparable.

## 2. Patched in this change

### 2.1 HumanEval runner: prompt helpers survive restated entry defs

`sixcat/code.py` used to truncate everything before a restated entry-point
`def`, which silently discarded prompt-provided helpers. For HumanEval/32
(`find_zero`, which relies on the prompt's `poly()` helper) that turned a
canonical item into a guaranteed `NameError` for any model that restates the
signature — most of them.

Now the harness concatenates `prompt + body` (a restated def simply overrides
the stub; later top-level defs win in Python), and falls back to the old
truncation only when concatenation cannot be guarded (degenerate bodyless-stub
shape). Covered by two new tests in `tests/test_code_safety.py`.

### 2.2 `--transport stdio` receipts can now be retried

`sixcat/run.py` records `transport` in the result JSON, and
`retry_plan_from_result` emits `--transport stdio` for stdio receipts. Before,
the documented Hermes retry flow regenerated an OpenAI-transport argv that
could never resume a stdio journal (identity mismatch aborted — fail-safe but
a dead end). Covered by two new tests in `tests/test_retry_merge.py`.

### 2.3 Data-lint suite: `tests/test_data_lint.py`

Ten invariants over the shipped data: MC answer keys within choice range
(MMLU/ARC/HellaSwag/WinoGrande/TruthfulQA, each with its real schema), GSM8K
`####` extractability, every shipped IFEval instruction id actually implemented
by `sixcat/instruct.py` (catching a shipped item silently zeroing under the
"unknown id fails closed" contract), kwargs/id-list alignment, tool-expectation
shapes, and challenge-selection indices referencing live rows. These are
sixcat-construction checks only; upstream-faithful quirks (§1) are exempt by
design.

### 2.4 `docs/harness-stdio.md`: the five things a driver author needs

Added the requirements discovered while running the world's first stdio-driven
battery: answer the unscored policy probe, drain stderr concurrently (stdout-
sequential drivers deadlock when the pipe buffer fills), apply `request_params`
to the raw model call (otherwise the sampling policy is decorative), send
`finish:"length"` on truncation, watch Windows pipe encodings
(`PYTHONIOENCODING=utf-8`), plus the OpenAI `tool_calls` answer shape and the
retry/`--ctx` notes.

### 2.5 Hermes skill: harness-driven target added

`SKILL.md` bumped to 0.5.0 and the target question now offers a fourth choice —
**🧜 Harness-driven stdio** — for models reachable only inside the harness
(no exportable key), with a pointer to the driver requirements and journal-
identity verification instead of the `/v1/models` guard. The README also now
documents `--policy-family` and `--concurrency`.

## 3. Recommended next (not patched here)

1. **Transport-aware preflight for stdio**: skip the two doomed HTTP probes
   against `stdio://harness`, replace the four `CTX_*`/`USAGE_*` warnings with
   one clear line, and let harness-reported `usage` feed the ETA logic.
2. **Suppress or tag `wall_tps` over stdio**: it measures harness round-trip,
   not model decode; `speed_source: stdio_harness` would keep receipts honest.
3. **Warn when `--api-key`/`SIXCAT_API_KEY` is set in stdio mode** (it is
   silently unused except for the doomed preflight probes).
4. **Subprocess-level stdio end-to-end test**: the current tests cover the
   client roundtrip and journal identity, but not `python -m sixcat
   --transport stdio` against a scripted responder — the layer where the
   stderr deadlock lived.
5. **`challenge-v2-clean` (optional)**: a selection profile that skips the
   upstream-noise items in §1, for users who want less anchor-inherited noise
   and are willing to lose tinyBenchmarks comparability.

## 4. What the review confirmed as sound

Journal identity isolation (stdio cannot resume an HTTP log, tested), the
`--concurrency 1` guard for stdio, fail-closed scoring (unknown IFEval ids,
blank answers, unsupported instructions), the challenge-fingerprint resume
blocks, compare guards against policy/scope mismatches, and the "never invent
the prefill/decode split" rule all behaved correctly under a real 121-request
stdio run that cross-validated the offline replay item for item.
