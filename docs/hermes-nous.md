# Qualify Nous Portal models from Hermes

## One-line requests

After loading the updated Sixcat skill, say:

```text
Run sixcat eval against the Hermes provider nous portal and the model Nemotron ultra free.
```

Or `/sixcat-eval nous portal Nemotron ultra free`. The operator instructions
below are reference material, **not a prompt the user must repeat**. The skill
uses strict sampling, thinking on, 20 items per category, concurrency 1 and a
30-minute run cap. Output names are generated automatically.
**Code execution is enabled by default.** Run all 120 items across all six
categories, including 20 HumanEval Code items executed and tested locally on
the machine running Sixcat. A container, VM or separate isolation approval is
not required. Do not add `--skip-code-exec` or reduce the scope unless the user
explicitly requests skipping Code. Genuine execution failures stay visible as
errors/incomplete results, not an automatic 100-item / Code N/A fallback.

Friendly names are resolved with a metadata-only command:

```bash
"$HERMES_PYTHON" -m sixcat.hermes resolve \
  --profile current --runtime-provider nous \
  --model-query "Nemotron ultra free" --json
```

The helper uses a fresh authenticated Nous `/models` catalog, not a hardcoded
model alias or the proxy's synthetic `/models`. It matches model ID/name tokens,
retains every token in the requested name, and returns an exact wire ID only
for one match. **No price filter by default:** paid, free and subscription-backed
targets are all supported. "Free" in a model name identifies a variant; it does
not automatically impose a spending constraint. A named variant must not be
replaced with some other zero-priced or subscription-backed model.

Only an explicit, separate user instruction such as "free models only" enables
`--free-only`. This optional catalog filter uses the existing label/pricing
checks; explicit nonzero or malformed prices fail that filter. Catalog labels,
subscription billing and zero prices are evidence, not proof of actual billing
or entitlement. Name matching without this flag does not reject a requested
model because its price is nonzero or unknown. The smoke request remains necessary.

If multiple variants match, the operator asks only which model to use. No match,
unavailable authentication or an actual local Python execution failure is a specific blocker,
not an excuse to silently substitute a model, provider, or different scope.
Missing optional settings never start a questionnaire. Existing live session
and profile defaults are not changed.

The skill must be loaded or discoverable. Trust a current checkout's project
skill or update the installed skill in the relevant Hermes profile; installing
the Python package alone does not register the skill in every conversation.
The operator should load the skill and read these instructions itself.

## What this measures

Use the deterministic Sixcat runner to evaluate the exact provider/model behind
Hermes, not the surrounding agent conversation. Hermes supplies provider routing,
OAuth and API adaptation; Sixcat supplies isolated task prompts and deterministic
graders. No Hermes persona, memory, skills, workspace files or real agent tools
are added to the target prompts. The Tools category supplies synthetic function
schemas and scores returned calls; it does not execute the target's calls.

The controller and target can be the same model, or different models. The
controller launches the runner and reads receipts; it must not answer questions,
read answer keys into model context, repair target responses or grade itself.

`hermes chat --provider nous --model MODEL -q PROMPT` is a real non-interactive
Hermes session, but is not a raw Chat Completions transport. Using it per Sixcat
question adds an agent harness and does not preserve the full task/tool-schema
contract. Benchmark actual Hermes tool execution, loops and recovery separately,
e.g. with an agentic benchmark; do not merge that score into raw-model Sixcat.

## Install in the correct environment

Sixcat requires Python 3.11+. The Python interpreter must also be able to import
Hermes and its dependencies. Installing Sixcat into the system Python or a
separate empty virtual environment does not automatically make Hermes importable.
Use the Python path from the Hermes installation that owns your Portal login:

```bash
# Set this to your actual Hermes virtual environment, not to the hermes CLI.
HERMES_PYTHON=/absolute/path/to/hermes-agent/venv/bin/python

"$HERMES_PYTHON" --version
"$HERMES_PYTHON" -m pip install -e .
"$HERMES_PYTHON" -c 'from hermes_cli.runtime_provider import resolve_runtime_provider; from agent.auxiliary_client import call_llm; import sixcat.hermes; print("Imports OK")'
```

Some installs use `.venv` instead of `venv`, an editable source checkout, or a
managed environment without pip. Use that environment's package manager, or
launch from the Sixcat checkout with its dependencies already present. Do not
run the evaluation as root just to work around a protected Hermes installation.
Create a non-privileged installation/profile instead. Do not overwrite a running
Hermes installation, re-login, or change its defaults merely to run a benchmark.

The native entry point is `python -m sixcat.hermes`; `sixcat-hermes` is also
installed as a console script. The old project-skill script remains compatible.

## Pick the exact target

For manual CLI use, use the exact model ID returned by `resolve` or already
shown for your Nous Portal entitlement; the conversational skill resolves it for you. Do not
assume all catalog models are free, or manufacture a `:free` suffix. The bridge
cannot attest prices, credits or free access. Even the smoke request consumes
quota. Nous provider authentication stays with Hermes; do not copy OAuth tokens
into command arguments, evaluation artifacts or chat messages.

```bash
MODEL='EXACT_MODEL_ID_FROM_YOUR_NOUS_PORTAL'

"$HERMES_PYTHON" -m sixcat.hermes inspect \
  --profile current --runtime-provider nous --runtime-model "$MODEL" \
  --policy strict --json
```

`inspect` resolves credentials and previews the selected policy. It does not call
the model, prove entitlement, verify that the backend is up, or prove that the
service is free. It explicitly reports `inference_verified: false` and
`billing_verified: false`.

For another saved Hermes profile, use `--profile PROFILE_NAME`. Omit both runtime
flags only when you deliberately want that profile's persisted default. To test
the model selected by an in-session `/model` switch, always pass both exact live
runtime flags. A child process cannot reconstruct a parent session override from
`config.yaml`. Outside a session, `current` honors the sticky active profile when
`HERMES_HOME` is unset; an explicit `HERMES_HOME` takes precedence.

## Verify connectivity, then benchmark

One real unscored request:

```bash
"$HERMES_PYTHON" -m sixcat.hermes smoke \
  --profile current --runtime-provider nous --runtime-model "$MODEL" --json
```

The smoke receipt records the returned text, requested and response model,
finish reason, usage when available, and `smoke_passed`. Failure is a diagnostic,
not a benchmark verdict. No benchmark starts automatically after a failed smoke.
A successful smoke still cannot attest the provider's actual underlying weights
or that your account will not be charged.

Optional context estimate (no live inference):

```bash
"$HERMES_PYTHON" -m sixcat.hermes preflight \
  --profile current --runtime-provider nous --runtime-model "$MODEL" -- \
  --policy strict --thinking on --limit 20 --json
```

The proxy's `/models` entry pins local routing; it is not the upstream catalog.
Upstream context/ETA may therefore be unknown. Do not replace unknown fields with
advertised maximums or confuse this metadata check with the smoke test.

Only when the user requests a smaller screening run (12 scored questions,
all six categories including local Code execution, **not** the standard 120):

```bash
"$HERMES_PYTHON" -m sixcat.hermes run \
  --profile current --runtime-provider nous --runtime-model "$MODEL" -- \
  --policy strict --thinking on --limit 2 --concurrency 1 \
  --max-minutes 5 \
  --artifact-id nous-model-screen-01 --out results/nous-model-screen-01.json \
  --no-resume
```

Standard full six-category qualification, with one fresh first response per task:

```bash
"$HERMES_PYTHON" -m sixcat.hermes run \
  --profile current --runtime-provider nous --runtime-model "$MODEL" -- \
  --policy strict --thinking on --limit 20 --concurrency 1 \
  --max-minutes 30 \
  --artifact-id nous-model-standard-01 --out results/nous-model-standard-01.json \
  --no-resume
```

**Local Code execution:** standard mode executes and tests all 20 HumanEval
completions in a temporary host-guarded subprocess using Sixcat's Python
interpreter. The existing timeout, output limits and AST/import guards remain.
This is not a security sandbox; extra isolation is optional, not a prerequisite.
Use `--skip-code-exec` only when the user explicitly opts out. Only that reduced
scope has 100 scored items and Code N/A; never use it as an automatic fallback.

Start with concurrency 1 on free/quota-limited routes. `--policy strict` fixes
sampling at temperature zero but does not guarantee deterministic provider
output. Thinking is a separate setting; use matching settings for comparisons.
Use `--policy vendor` only with a reviewed matching family, and record its resolved
policy and budgets. Thinking-on permits hidden or unrevealed reasoning; some
reasoning-only models will not honor an off switch.

A 30-minute cap may leave a run incomplete. Check final category counts and the
completion flags, not just process exit zero. To continue unfinished work, rerun
the **same exact command and artifact identity**, replacing `--no-resume` with
`--retry remaining`. Keep first-response scores; do not selectively regenerate
failures and publish the improved diagnostic as pass@1. Different models, scopes,
policies and quantizations require separate output files.

## Ask one Hermes model to operate the test against another

Normally use the one-line request above. The following expanded instruction is
an optional reference for custom overrides, not required user input:

```text
Run Sixcat against the exact model TARGET_MODEL_ID through provider nous,
using profile current. You are the operator, not the model being graded.
Use the Python 3.11+ environment that contains Hermes and Sixcat.
Do not switch my current session model or change persisted configuration.
Run inspect with strict policy, then one smoke request. Stop and report the
actual error if authentication, route verification or the smoke test fails.
Then run --policy strict --thinking on --limit 20 --concurrency 1
--max-minutes 30 --artifact-id TARGET_RUN_ID
--out results/TARGET_RUN_ID.json --no-resume.
Run all 120 items across six categories. Execute and test the 20 Code items
locally using Sixcat's existing Python checker. Do not skip Code or require a
separate container/VM. Report its measured score and correct/scored counts.
Do not ask setup questions for settings already given. Do not read answer keys,
answer any benchmark question yourself, repair answers, retry scored failures,
change providers/models, use a fallback or run a speed/concurrency sweep.
Summarize only saved receipts, including counts, incomplete status, errors,
policy/thinking settings, latency and usage when available. Do not invent TPS
or claim free billing has been verified. No credentials in output.
```

The standard instruction includes all 120 items and local Code execution.
For a non-interactive controller, save the filled-in instruction to a file
and use Hermes' real CLI:

```bash
hermes chat --provider nous --model "$CONTROLLER_MODEL" \
  --query-file sixcat-controller.txt
```

The controller's model/provider above is independent of `--runtime-model` and
`--runtime-provider` inside the benchmark command. Only use a controller route
you have approved for usage/cost. Prefer calling the deterministic runner
directly from an existing Hermes terminal tool: an additional controller agent
adds overhead and potential failure points without improving the grading.

## Failure handling and transport limits

The adapter requests the streaming path of Hermes' `call_llm`, which bypasses
Hermes' non-stream auxiliary recovery/provider-fallback ladder, then assembles
the result into one completion. It does not retry as non-stream when a provider
fails. Resolved provider/model identity is checked before and after consumption.
This is a client-side route guarantee, not attestation of Portal's internal
routing, installed middleware, model weights, price, or server cancellation.

Tool-call argument fragments, reasoning text, refusal, usage and finish reasons
are preserved. A stream interrupted before its terminal finish reason is an
unscored transport failure, not a scored partial answer. A normal completed
`finish_reason=length` response remains a real truncated first response.
HTTP provider status codes such as 401/403/429/5xx are preserved when available.

The loopback response is complete JSON rather than downstream SSE. Do not use
this bridge for `sixcat speed` or auto-concurrency/TTFT measurements. End-to-end
latency can include provider, network and adapter overhead; missing provider
telemetry remains missing. The benchmark deadline stops local scoring/work, but
cannot guarantee that a provider cancels already-dispatched computation.

Source contracts reviewed: Sixcat base `841f90a4843745675c771ac4b5ae9205049b42c0`;
Hermes upstream `0ab8010b3c211ff323fd8602ff0fbdfc4d96cb1b`.
Official Hermes docs: https://hermes-agent.nousresearch.com/docs/user-guide/cli/
and https://hermes-agent.nousresearch.com/docs/guides/run-hermes-with-nous-portal.
Mock/local tests do not establish that any particular live Portal model works.

## Optional public results

After all 120 questions are scored, the skill asks whether to publish a
Community Results PR. No extra evaluation prompt is needed. Publication requires
an explicit yes, preserves the original JSON/journal, and uses a public export
with model/source/quant/engine/wrapper metadata. Low scores are eligible. See
[the submission guide](../community/README.md) for preview/export commands and
privacy details. This feature is unreleased on main; v0.8.3 does not contain it.
