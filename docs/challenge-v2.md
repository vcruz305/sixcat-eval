# challenge-v2: a harder, opt-in 120

**Status: unreleased on main, uncalibrated.** `challenge-v1` remains the default
and the only selection eligible for Community Results. Nothing about v1 changed:
its content-addressed benchmark fingerprint is byte-for-byte the same, and a test
pins that.

```bash
python -m sixcat \
  --base-url http://127.0.0.1:8085/v1 --model my-model \
  --profile challenge-v2 \
  --policy vendor --thinking on --concurrency 4 --max-minutes 30 \
  --out results/my-model.v2.json
```

Use a fresh `--out`/`--log` for v2. A v1 journal will not resume under v2 or the
other way round, and `sixcat compare` refuses to mix the two.

## Why

By v0.8.3 the standard set had stopped separating strong local models:

- **Math** (tinyGSM8K) was 95-100 for every fully posted row, 100 for most.
- **Tools** and **Code** averaged about 90 and 88.
- **Truth** presented each item's options in source order, and in
  tinyTruthfulQA the correct option is always first. A model that answers "A"
  to everything scores 100 on v1 Truth.
- Much of the remaining headroom in **Knowledge** was noise. Choosing items by
  failure rate concentrates mislabeled and ambiguous ones (see
  [eval-run-findings.md](eval-run-findings.md) section 1).

## What is in it

Same shape as v1: six categories, 20 items each, one first response per item,
deterministic local graders, unweighted mean of category scores.

| Category | v1 | v2 | Built by |
|---|---|---|---|
| Knowledge | tinyMMLU / ARC / HellaSwag / WinoGrande, 5 each | 20 ten-option MMLU-Pro questions | `tools/select_v2_knowledge.py` |
| Math | tinyGSM8K | 20 original problems in four tiers | `tools/build_v2_math.py` |
| Truth | tinyTruthfulQA MC1, source order | tinyTruthfulQA MC1, options shuffled per item | `sixcat/challenge_v2.py` |
| Instruct | IFEval-100, 1-3 constraints | 20 original prompts with stacked constraints | `tools/build_v2_instruct.py` |
| Code | HumanEval | 20 original function-level problems | `tools/build_v2_code.py` |
| Tools | 5 flat tools | 18 confusable tools, nested/typed args, 4 abstentions | `sixcat/v2_tools.py` |

**Knowledge.** MMLU-Pro publishes per-question outputs for 48 model runs. Items
were filtered for ten distinct options, a 10-40% pass rate across those runs,
a clear gap in overall strength between runs that got the item right and runs
that did not, and agreement between the answer key and the one 2026 frontier
run in the set. That list was then read by hand and each key re-derived; items
with a wrong or debatable key, garbled text or a give-away format were dropped.
One candidate with a plainly wrong key was caught this way. Options are shown
in published order because some refer to other options by letter.

**Math.** Tier 1 is long word problems with distractors; tier 2 is rates,
mixtures and work-backwards; tier 3 is counting, number theory and lattice
paths; tier 4 is probability and long exact simulation. Every answer is computed
by code and, wherever a second method exists, cross-checked by brute force or
simulation before the row is written. The grader is the v1 exact-number parser,
with one addition: a currency symbol straight after `####` is ignored.

**Truth.** Rows are ranked by number of answer options (more distractors
first). Row 7 ("Haslam") and two duplicate rows are skipped. Each item's
options are put in a fixed order derived from a hash of its key, so prompts are
identical on every run and platform but the key is no longer always "A".

**Instruct.** Eighteen prompts carry four to six separate checks; two ask for a
typed JSON object. New checks cover per-line word counts, acrostics, exact word
totals, unique words, alliteration, number sums and line patterns. None uses
language detection. Each item ships with a reference answer that passes all of
its checks, so no item is unsatisfiable (v1 inherits one IFEval item that no
response can pass).

**Code.** Written for this benchmark; nothing is copied from HumanEval or a
problem site. Each reference solution is checked against an independent
brute-force or second implementation on 400 seeded random inputs, and the
hidden tests include large inputs so quadratic solutions time out. The existing
guarded runner executes them. The prompt tells the model the runner's rules
(allowed imports, no top-level code, no underscore attributes, no deep
recursion), because breaking them fails the item regardless of correctness.

**Tools.** Look-alike tools (read vs inspect, send vs draft, workspace search vs
web search), enums chosen from a description, nested and array arguments, values
the model must derive (a duration, UTC timestamps, a Fahrenheit conversion), and
four cases where the right answer is no tool call. Grading is exact, with two
fairness rules: an optional argument passed with its schema default counts as
omitted, and `path` ignores a leading `./` and trailing `/`.

## What it does not do yet

- **No calibration.** No model has been run against v2. The answer keys are
  verified; the difficulty is not. Expect to drop or swap items after the first
  panel run, and treat early v2 numbers as provisional.
- **No Community Results.** The v2 manifest is not in the compatibility
  registry, so `sixcat submit` rejects v2 results.
- **No `--full`.** v2 has exactly 20 items per category; `--limit 1..20` works
  for smoke tests.
- **No Hermes skill path.** The skill and `sixcat.hermes` still run v1.
- **Not comparable with v1.** Different items. Keep the tables separate.
- **Single turn only.** Tools items do not feed a tool result back for a
  dependent second call.
- **v1 is untouched, including its known issues.** The always-"A" Truth order
  and the `parse_mc_answer` crash on an empty multiple-choice answer are still
  present in v1, because fixing them edits files the approved v1 fingerprint
  hashes. v2 scores an empty answer as a miss.

## Rebuilding and checking the data

```bash
python tools/build_v2_math.py --check
python tools/build_v2_instruct.py --check
python tools/build_v2_code.py --check
python tools/select_v2_knowledge.py /path/to/MMLU-Pro --check   # needs a checkout of MMLU-Pro
python -m sixcat rescore results/my-model.v2.json --out results/my-model.v2.rescored.json
```

The first three also run in CI through `tests/test_challenge_v2.py`, together
with an end-to-end run against a local scripted endpoint that answers from the
keys and must score 120/120.

Editing any v2 data file, `sixcat/challenge_v2.py`, `sixcat/v2_tools.py` or
`sixcat/v2_instruct.py` changes the v2 benchmark fingerprint, exactly as for v1.

## Attribution

Knowledge items come from [MMLU-Pro](https://github.com/TIGER-AI-Lab/MMLU-Pro)
(Apache-2.0), which draws on MMLU, STEMEZ, TheoremQA and SciBench. Truth items
come from tinyTruthfulQA as in v1. Math, Instruct, Code and Tools items are
original to this repository and are covered by its MIT license.
