# Hermes and Nous Portal

**New in v0.8.0:** qualify the exact model selected in Hermes, or ask one Hermes
model to operate a Sixcat run against another. The installed entry points are
`python -m sixcat.hermes` and `sixcat-hermes`. Hermes supplies provider routing and
authentication; Sixcat sends fresh task requests and grades the saved responses.
The target does not receive the controller's conversation, persona, memory,
workspace files or real agent tools. The operator can be the same model as the
target, but must not answer or grade its own benchmark questions.

## Just ask your agent

With the **current Sixcat skill loaded**, name any supported provider and model:
`Run sixcat eval against the Hermes provider PROVIDER and the model MODEL.`
One example is:

```text
Run sixcat eval against the Hermes provider nous portal and the model Nemotron ultra free.
```

Or invoke it explicitly: `/sixcat-eval nous portal Nemotron ultra free`.
You do not need to provide an exact ID, an operator prompt, shell variables or a
results path. The skill resolves the name from your live authenticated Nous
catalog and handles inspect, smoke, launch and saved-result reporting.
**No price filter by default:** free, paid and subscription-backed models can
all be selected. "Nemotron ultra free" is only an example model name; the word
"free" stays part of that name, not an inferred spending constraint. Apply a
price filter only when the user separately requests one, such as "free models
only" (`--free-only`). Do not silently substitute any different model or variant.
It asks only when a real model ambiguity or blocker requires your input.

Defaults are strict sampling, thinking on, 20 items per category, concurrency 1,
a 30-minute run cap, and unique result paths. **Code execution is enabled by default.** Run **all 120 items across all six categories**, including 20 HumanEval
Code items tested locally on the machine running Sixcat. No container, VM or
separate isolation approval is required. Do not automatically add
`--skip-code-exec` or substitute a 100-item / Code N/A run. Skipping Code is an
explicit user opt-out only; other explicit settings also override defaults.

The instructions must be discoverable: load the updated project skill from a
trusted checkout, or install/update the skill in your Hermes profile. A README
on GitHub or a Python package alone is not automatically loaded into every
Hermes conversation. An older copied skill keeps its older instructions until
updated. This is one-time setup, not a long prompt for every evaluation.
See [the one-line operator workflow](hermes-nous.md#one-line-requests).

## Install alongside Hermes

Use **Python 3.11+ from the environment containing Hermes**. Installing Sixcat into
an unrelated system Python or empty virtual environment is not enough. From this
checkout:

```bash
# Replace this with your actual Hermes environment; some installs use .venv.
HERMES_PYTHON="/absolute/path/to/hermes-agent/venv/bin/python"
"$HERMES_PYTHON" --version
"$HERMES_PYTHON" -m pip install -e .
"$HERMES_PYTHON" -m sixcat.hermes --help
```

To pin the release without a source checkout, install
`git+https://github.com/vcruz305/sixcat-eval.git@v0.8.3` into that same environment.
The [project-local Hermes skill](../.hermes/skills/sixcat-eval/SKILL.md) remains
available: start Hermes in the checkout and trust its project skills with
`hermes skills trust`. The old `scripts/hermes_runner.py` entry point remains
compatible with the installed runner.

## Select a model, check it, then run

Choose the **exact model ID already available to your Nous Portal account**.
Do not add a `:free` suffix unless it is part of that actual ID. A model listing
or successful request does not establish that usage is free.

```bash
MODEL="EXACT_MODEL_ID_FROM_YOUR_NOUS_PORTAL"

# Configuration/authentication resolution only; no inference validation.
"$HERMES_PYTHON" -m sixcat.hermes inspect \
  --profile current --runtime-provider nous --runtime-model "$MODEL" \
  --policy strict --json

# One real, unscored request. It consumes provider quota. Stop on failure.
"$HERMES_PYTHON" -m sixcat.hermes smoke \
  --profile current --runtime-provider nous --runtime-model "$MODEL" --json
```

For a live in-session `/model` selection, pass **both** exact runtime flags.
`--profile current` alone cannot reconstruct a parent conversation's model
switch from the profile's saved configuration. To evaluate a different model,
change `--runtime-model` without changing your current conversation or saved
Hermes defaults. To use another saved profile, replace `current` with its name;
omit both runtime flags only when you deliberately want that profile's persisted
default. An explicit `HERMES_HOME` takes precedence over the sticky active profile.

After a successful smoke test, start conservatively with one concurrent request:

```bash
"$HERMES_PYTHON" -m sixcat.hermes run \
  --profile current --runtime-provider nous --runtime-model "$MODEL" -- \
  --policy strict --thinking on --limit 20 --concurrency 1 \
  --max-minutes 30 \
  --artifact-id nous-candidate-01 --out results/nous-candidate-01.json \
  --no-resume
```

**This requests all 120 scored items across six categories, including Code.**
Generated Python is executed and tested locally with the existing HumanEval
checker, temporary directories, timeouts and guards. The checker is **not a
security sandbox**, but a separate sandbox is not a prerequisite for this mode.
Do not silently reduce the scope after an execution error; report the actual
error or incomplete counts. Only an explicit `--skip-code-exec` request reduces
standard scope to 100 items with Code N/A. An explicitly requested smaller
screening run can use `--limit 2 --max-minutes 5`: 12 items including Code,
not the standard 120-item qualification.

Optional `preflight` estimates context without making a model inference call:

```bash
"$HERMES_PYTHON" -m sixcat.hermes preflight \
  --profile current --runtime-provider nous --runtime-model "$MODEL" -- \
  --policy strict --thinking on --limit 20 --json
```

Unknown upstream context/ETA remains unknown. `inspect` and `preflight` are not
substitutes for `smoke`, and none of these commands verifies account billing.

## Let a Hermes LLM operate the evaluation

In an existing Hermes conversation, use the one-line request above. The agent
loads the skill and constructs the commands itself, then reports JSON/JSONL receipts. It must not
read answer keys, answer benchmark questions itself, edit target responses,
change providers, or selectively retry scored failures. A supplied provider/model is enough; omitted optional settings use the documented defaults.

For a separate **non-interactive controller** with this skill loaded, the same
one-line request can be supplied through `-q` or saved to `sixcat-controller.txt`:

```bash
hermes chat --provider nous --model "$CONTROLLER_MODEL" \
  --query-file sixcat-controller.txt
```

`CONTROLLER_MODEL` is the operator; `--runtime-model` inside the benchmark command
is the model being graded. The two can be identical or different. Prefer an
existing Hermes terminal tool calling the deterministic runner directly when a
second controller is unnecessary. Do not use `hermes chat -q` per question as a
replacement for Sixcat's raw-model transport: that measures an agent-assisted
configuration rather than the same isolated model contract. See the
[official Hermes CLI documentation](https://hermes-agent.nousresearch.com/docs/user-guide/cli/).

## Reliability and limits

The bridge uses Hermes' streaming call path to bypass the non-stream auxiliary
provider-fallback ladder and checks the resolved provider/model before and after
collecting the completion. It never retries as a non-stream auxiliary call.
This pins the Hermes client-side route; it does not attest Portal-internal
routing, installed middleware, model weights, price, or server cancellation.
Credentials stay with Hermes rather than being copied into benchmark commands.

Tool controls, fragmented tool-call arguments, reasoning, usage and finish
reasons are preserved. Interrupted streams are unscored transport errors;
completed `finish_reason=length` responses remain real truncated first responses.
The Tools category scores synthetic function calls without executing them.

Use fresh artifact IDs/output paths for different targets. Check final scored
counts and incomplete status, not only exit zero. Resume unfinished items with
the same settings and `--retry remaining` instead of `--no-resume`; later failure
retries must not replace first-response scores.

**Use a direct HTTP endpoint for speed tests.** The Hermes bridge returns complete
JSON downstream, not SSE token streams, so do not use it for `sixcat speed`,
`--auto-concurrency`, or client TTFT measurements. No live Portal inference or
billing entitlement was verified during this release's mock/loopback tests.

The [full Hermes + Nous Portal guide](hermes-nous.md) includes setup,
troubleshooting, exact commands and a copyable controller prompt.
