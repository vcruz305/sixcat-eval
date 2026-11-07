---
name: sixcat-eval
description: Run Sixcat from a provider and model name.
version: 0.8.3
author: Victor Cruz (vcruz305), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [llm-evaluation, local-llm, benchmarking, sixcat]
    related_skills: []
    requires_toolsets: [terminal]
---

# Sixcat Conversational Operator

Run Sixcat against either the exact model backing the current Hermes session or
an alternate OpenAI-compatible endpoint. A provider and model name are enough:
resolve them, use the defaults below, run the evaluation, and report saved receipts.
Do not turn a concrete target request into a configuration questionnaire.

## One-line requests: default path

This path takes precedence over the optional interactive wizard below.
The user should be able to say exactly:

> Run sixcat eval against the Hermes provider nous portal and the model Nemotron ultra free.

Or use `/sixcat-eval nous portal Nemotron ultra free`. A provider and model name
are sufficient. **Do not ask for policy, thinking, limits, concurrency, output
paths, or code mode before starting.** Those are operator defaults, not required
user input. Use an explicit user override whenever one is supplied.

1. Map the provider names `nous portal`, `Nous Portal`, and `nous` to `nous`.
   Keep the controller on its current model. Locate the interpreter and existing
   authentication; never ask the user to paste credentials or switch models.
2. Resolve a friendly name from the live authenticated Nous catalog with:
   `python -m sixcat.hermes resolve --profile current --runtime-provider nous --model-query "Nemotron ultra free" --json`.
   Substitute the actual requested phrase. **No price filter by default.**
   Free, paid and subscription-backed targets are all allowed. "Nemotron ultra
   free" is an example name, not a budget requirement; retain every name token,
   including "free", to select the requested variant. Only add `--free-only`
   when the user separately requests a price restriction (e.g. "free models only").
   Never infer that restriction merely from a model ID/display name. Do not make
   up a wire ID, choose a different variant or use a static fallback catalog.
   The resolver returns an exact `model` only for one match. If `status=ambiguous`,
   ask one targeted model-choice question; if not found, report that no matching
   model was found. Catalog pricing is evidence, not a billing guarantee.
3. Use profile `current`, policy `strict`, thinking `on`, `--limit 20`,
   `--concurrency 1`, and `--max-minutes 30`, unless overridden. Generate a unique
   filesystem-safe model/timestamp RUN_ID and JSON/JSONL paths automatically.
4. Run **all 120 items across all six categories**, including all 20 HumanEval
   Code items. **Code execution is enabled by default.** Execute and test the
   generated Python locally on the machine running Sixcat, using its existing
   interpreter and guarded subprocess checker. A separate container, VM or
   isolation approval is not a prerequisite. Do not add `--skip-code-exec`,
   reduce the run to 100 items, or label Code N/A unless the user explicitly
   requests skipping Code. Keep the existing timeout, temporary-directory,
   output, environment and AST/import guards; they are not a security sandbox.
   A real execution error or deadline produces an error/incomplete receipt,
   not a silent switch to a five-category run.
5. Run inspect and one smoke request against the resolved exact model/provider.
   Stop on auth, route or smoke failure. Run the benchmark with the chosen
   defaults and `--no-resume` in a fresh output path. Use tracked process/live
   status tools and report the saved results, errors and completion counts.
   Then follow the Public Community Results section: ask once about publication,
   never publish without explicit approval.
6. Never read answer keys into model context, answer tasks yourself, alter
   completions, substitute providers, or rerun scored failures to inflate scores.
   No speed/auto-concurrency sweep, release-upgrade dialogue or setup form.
   An optional release check may be informational; never downgrade a newer main
   checkout to an older tag or update software without authorization.

Only a real blocker (missing authentication/installation, a local Python
execution failure, no model match) or genuine model ambiguity interrupts this path.
The absence of a container or VM is not a blocker for local code execution.
A long operator prompt, exact ID supplied by the user, and manual result paths
are **not prerequisites**. The detailed commands belong in this skill and `docs/hermes.md`.

## Non-interactive and Nous Portal runs

Apply the same one-line defaults to `hermes chat -q` instructions. Do not call
`clarify` in non-interactive mode; fail with a specific diagnostic and candidates
when a real choice is needed. Do not invoke `hermes model`, `hermes setup`, or
upgrade software. The optional wizard below is only for users who explicitly
ask to customize settings or need help choosing an unspecified target.

Use the Python 3.11+ interpreter containing Hermes and Sixcat, not whichever
`python` the terminal happens to resolve. The installed entry point is
`python -m sixcat.hermes`; `scripts/hermes_runner.py` remains a compatibility shim.
See `docs/hermes.md` and `docs/hermes-nous.md` for setup, smoke tests, exact
commands and controller prompts. `inspect` resolves configuration/authentication but does not verify
inference or that a model is free. `smoke` sends one unscored real request and
consumes provider quota. A smoke failure is not a Sixcat benchmark score.

For Nous Portal, always pin `--runtime-provider nous` and the exact model ID
already available to the user. Do not add a `:free` suffix unless it is part of
the actual ID. Never use provider `auto` or substitute a different model. Default to
concurrency 1 for quota-limited Portal routes; do not auto-tune concurrency there.
One Hermes LLM may operate this deterministic runner against another LLM. The
controller must not answer, edit or grade the target's responses itself, and
must not read answer keys or `offline/answers*` into any model context.

Running the same model in a fresh raw request is valid self-qualification.
Asking an agent to read the tests/solutions and then report its own score is not.
A full `hermes chat -q` session adds persona, memory and tools; evaluate that
separately as an agent-assisted configuration, not the raw Sixcat leaderboard.

## 0.8.3 execution contract

Keep Standard at 120 scored questions and 30 minutes. Do not automatically enable
full mode or repeated runs. For HTTP, offer `--concurrency 2` or `4` when the server
has capacity; default 1 is conservative for a memory-tight local endpoint. The
scheduler interleaves categories while retaining their frozen hardest-first
orders. Stdio is serial and requires concurrency 1.

The deadline covers active requests and preflight. Save and label incomplete
results; do not promise the full 120 can finish on any given hardware. `both`
shares one total deadline. Live throughput comes from `execution.throughput_tps`,
not the historical request-weighted `suite_tps`. Preserve each execution segment.

For a **direct OpenAI-compatible HTTP endpoint**, offer `--auto-concurrency`
when the user wants Sixcat to find the throughput knee before the scored run.
The calibration is unscored, uses synthetic prompts rather than benchmark
questions, and shares the 30-minute invocation budget. For a speed-only request,
use `python -m sixcat speed`; report client TTFT/E2E/TPOT percentiles separately
from provider-native prefill/decode/queue metrics. Recommend `--samples 100`
when p99 itself is an acceptance criterion.

Do **not** use `--auto-concurrency` or `sixcat speed` through the current Hermes
runtime loopback bridge: that bridge returns complete JSON responses rather than
SSE token streams, so it cannot produce valid client TTFT. Use a direct
OpenAI-compatible endpoint for streaming performance measurement.

Use distinct artifact IDs/output paths for different quantizations. An operator
artifact ID and server metadata are recorded evidence, not proof of the weights.
Do not silently resume old parser-v4 journals into v5. Never present selective
failure-retry diagnostics as an improved first-response score. Offline `rescore`
reuses saved generations; `export-evalplus` only exports and does not execute an
external benchmark. Both are opt-in.

## When to Use

- The user asks Hermes to test, benchmark, compare, or score a model with Sixcat.
- The user invokes `/sixcat-eval` inside this repository.
- The user asks for live status from an existing Sixcat JSONL journal.
- The user asks to retry failed or remaining items from an existing Sixcat receipt
  against the current Hermes session model.
- The user asks to find the best serving concurrency, TTFT, p95/p99 latency,
  prefill/decode speed, or a speed-only benchmark against a direct HTTP endpoint.

Do not use this skill to launch, kill, swap, download, or quantize a model.
Hermes-runtime mode may create a short-lived loopback proxy owned by the tracked
Sixcat process; it must close in `finally`. Do not start, stop, or replace the
actual model server. If no target is reachable, report that prerequisite.

## Prerequisites

- Start Hermes inside the Sixcat git checkout.
- Trust its project skills once with `hermes skills trust` from the project root.
- Python 3.11+ and the repository dependencies must be available.
- An alternate target server must expose `/v1/models` and `/v1/chat/completions`.
- Hermes-runtime mode requires a resolvable profile model/provider and its
  existing provider authentication. The runner never prints those credentials.
- For an authenticated endpoint, keep the key in `SIXCAT_API_KEY`; never print it.
- An API key requires exactly one explicit `SIXCAT_BASE_URL` or `--base-url`; the
  preflight refuses to broadcast one credential across discovery candidates.
- Without a credential, optional `SIXCAT_BASE_URL` can select the endpoint without
  putting it in chat; otherwise discovery probes common localhost ports unauthenticated.

## Quick Reference

- Standard run: `--limit 20 --max-minutes 30` means **20 scored items per
  category**, about 120 scored rows total. It never means 20 per source dataset.
- Current scorer/parser identity: `v5`; older `v2`/`v3`/`v4` receipts are readable
  but non-comparable to parser-v5 runs.
- Vendor-recommended temperature/settings use seed `1` for repeatability when a
  reviewed model mapping exists. Custom mode may use any integer or no seed.
- New run: use `--no-resume` and a fresh artifact basename.
- Live status: summarize the JSONL with the bundled status helper.
- Completion: require a final JSON result, a zero process exit code, AND full
  scored-category counts for the requested scope; exit zero alone is not enough.
- Release check: `scripts/check_release.py --json` before the first question.

## Procedure (optional interactive wizard)

Skip this entire wizard for the one-line target path above. It is for an
explicit request to customize options or help choosing a missing target only.
If a target is already known, do not ask which target to evaluate again.

Hard rule for every question, including target, sampling, size, code,
thinking, release update, retry mode, and vendor-family adopt:

- Call `clarify` with a non-empty `choices` array of 2-4 strings.
- Never send a `clarify` that is only a question. On Telegram that becomes a
  bare `?` prompt with no buttons.
- Never put the options only in the question text or in a chat message.
- Never send prose like "now the setup form" instead of the `clarify` call.
- A batched `questions` array is allowed only when **every** item has its own
  `choices`. Telegram asks those one at a time; missing `choices` on any item
  drops the buttons.
- Preferred Telegram shape: one `clarify` whose `questions` list has four
  items, each with `question` plus `choices`.

### 0. Check for a newer Sixcat release

For interactive setup, before any target, retry, or sampling question, run:

```text
terminal(
  command='python "${HERMES_SKILL_DIR}/scripts/check_release.py" --json',
  workdir='<project-root>'
)
```

- If `status=skipped`, continue. Do not block the skill on a network failure.
- If `comparison=current` or `newer_than_release`, continue immediately to the
  next procedure step. Do not narrate a no-op check.
- If `update_available` is true, immediately ask one option-only `clarify`
  before any other Sixcat question:

  - **⬇️ Update to latest release (recommended)** — `git fetch origin --tags`,
    `git checkout <latest_tag>`, then `python -m pip install -e .`. Re-read this
    skill after the checkout. Do not force the update if the worktree is dirty;
    report the dirty files and stop.
  - **➡️ Continue with this checkout** — use the local commit as-is.

Do not start the target or retry questionnaire until that choice is answered.

### Existing-receipt retry (short path)

If the user already named an existing result/journal and asked to retry failed,
remaining, or incomplete items, **do not** start the new-run target/sampling
questionnaire. Do not use `--no-resume`.

1. Immediately confirm only what is still missing, with options: **🔁 Retry
   failed only**, **▶️ Continue remaining only**, **🧩 Retry failed and remaining**.
2. Default target is the **current Hermes session model**. Inspect it only after
   the retry mode is known.
3. Run `python -m sixcat retry-plan <result.json> --retry <mode> --json` from the
   project root. That prints the exact merge argv (policy, temperature, thinking,
   limit, `--request-timeout`, `--log`, `--out`).
4. The live Hermes model/provider must match `plan.model`. If they differ, refuse
   to merge; a different model is a new run, not a continuation.
5. Launch through `hermes_runner.py` with those argv and **no** `--no-resume`.
   A loopback proxy port may change only when the journal recorded the same verified upstream identity; otherwise start a fresh journal.
6. Report the rewritten JSON as one merged receipt.

### 1. Ask which target to evaluate

Only when the target cannot be inferred from the request or live session, ask:

> 🎯 Do you want to run Sixcat against the model I am currently running,
> another Hermes profile, an alternate OpenAI-compatible endpoint, or this
> harness directly over stdio?

Use one `clarify` question **with `choices`**. Do not write the numbered list
into the question text. Call it like this:

```text
clarify(
  question='🎯 Do you want to run Sixcat against the model I am currently running, another Hermes profile, an alternate OpenAI-compatible endpoint, or this harness directly over stdio?',
  choices=[
    '🧠 Current Hermes session model — evaluate the exact live model through the raw-model bridge',
    '👤 Another Hermes profile — that profile’s configured default model',
    '🔌 Alternate OpenAI-compatible endpoint — an already-running /v1 server',
    '🧜 Harness-driven stdio — this agent answers Sixcat’s raw requests directly (no exportable key needed)'
  ]
)
```

1. **🧠 Current Hermes session model (recommended)** — evaluate the exact model
   and provider powering this conversation through the clean raw-model bridge;
   do not include this agent's persona, tools, memory, or conversation.
2. **👤 Another Hermes profile** — evaluate that profile's configured default
   model using the authentication already stored for that profile.
3. **🔌 Alternate OpenAI-compatible endpoint** — evaluate an already-running
   `/v1/chat/completions` server selected through its `/v1/models` identity.
4. **🧜 Harness-driven stdio** — the agent itself answers Sixcat's JSONL
   `complete` requests on stdin (`--transport stdio`). Use this when the model
   is reachable only inside the harness and has no exportable API key. This
   is not needed for Nous OAuth: use the raw-model bridge for Nous. Stdio is a
   harness-assisted configuration and is not automatically comparable. Follow
   [docs/harness-stdio.md](../../../docs/harness-stdio.md): answer every request
   including the unscored policy probe, apply `request_params` to the underlying
   model call, send `finish:"length"` on truncation, and use the OpenAI
   `tool_calls` shape for tool answers. Verification in step 8 uses the journal
   identity (`transport=stdio`) instead of the `/v1/models` guard.

Do not silently choose a localhost model server. The default recommendation is
the current caller's exact live model and provider, including a session `/model`
override. Do not substitute the profile's configured default after a session
model switch.

For the current session, inspect the exact runtime without exposing credentials:

```text
terminal(
  command='python "${HERMES_SKILL_DIR}/scripts/hermes_runner.py" inspect --profile current --runtime-model <live-model> --runtime-provider <live-provider> --json',
  workdir='<project-root>'
)
```

The live model/provider come from the current Hermes runtime metadata. For
another profile, ask which profile, then omit the two `--runtime-*` arguments so
the runner resolves the profile's configured default route.

### 2. Immediately ask the remaining questions

Only when the user explicitly requested interactive customization, use the
setup form below for settings still missing. Merely naming a provider/model
never triggers this form: use the one-line defaults instead.

Use a **single** `clarify` call with **four** items in `questions`. Every item
must include a non-empty `choices` array. Do not ask these as plain chat text and
do not omit the choices from the tool call. Example shape:

```text
clarify(
  questions=[
    {
      'question': '🎚️ How should Sixcat sample this model?',
      'choices': [
        '🏷️ Vendor-recommended settings (recommended when mapped) — reviewed model-card temperature/top-p/top-k/min-p + seed 1',
        '🧊 Deterministic baseline — temperature 0 for cross-run comparison',
        '⚖️ Compare both — run strict and vendor profiles separately',
        '🎛️ Custom settings — I’ll enter an exact temperature'
      ]
    },
    {
      'question': '🧪 How large should this run be?',
      'choices': [
        '⭐ Standard (recommended) — 20 per category, ~120 scored rows, 30-minute cap',
        '⚡ Quick — 10 per category, ~60 scored rows, 30-minute cap',
        '📚 Full — all 884 shipped rows, 30-minute cap unless explicitly uncapped',
        '🔢 Custom — choose a per-category limit'
      ]
    },
    {
      'question': '🐍 HumanEval runs generated Python in a guarded host subprocess, not a security sandbox. What should Sixcat do?',
      'choices': [
        '✅ Keep HumanEval enabled (default) — run all 20 Code items locally with the existing guards and timeout',
        '🛡️ Explicitly skip Code for this run — reduced scope, Code N/A'
      ]
    },
    {
      'question': '🧠 Should model reasoning/thinking be enabled?',
      'choices': [
        '🧠 Thinking on (recommended when supported) — allow the model’s reasoning mode',
        '⚡ Thinking off — no reasoning trace'
      ]
    }
  ]
)
```

If this Hermes surface cannot provide a `clarify` tool with explicit choices,
show those same four option groups as structured numbered options and wait for
answers. Do not silently choose defaults.

If the user chooses **Custom** sampling, ask one more `clarify` with `choices`
for temperature: `0`, `0.2`, `0.6`, `1.0`. Then ask top-p as another
option-only `clarify`: `1.0`, `0.95`, `0.9`, `Other / omit`. Ask for a typed
number only after the user chooses `Other / omit` and then chooses `Other` from a
second option-only question. Optional top-k/min-p/seed follow the same pattern.

If the user chooses **Custom** size, ask one more `clarify` with `choices`:
`5 per category`, `10 per category`, `20 per category`, `Other`. Ask for a typed
integer only after `Other` is selected. Only if the user explicitly requests
skipping code execution, state that Code will be `n/a` and excluded from the
overall mean. Never choose that reduced scope automatically.

### 3. Resolve the target after all answers exist

**Current/other Hermes model**

Run inspect only now. It returns JSON with one endpoint/model/provider and a
policy preview. For another profile, replace `current` with the selected profile.
The helper resolves the selected profile's `config.yaml` and calls Hermes'
provider/auth resolver. It honors explicit live model/provider overrides; it
never changes your saved default model. A sticky profile is honored when
`HERMES_HOME` is not already set.

```text
terminal(
  command='python "${HERMES_SKILL_DIR}/scripts/hermes_runner.py" inspect --profile current --runtime-model <live-model> --runtime-provider <live-provider> --json --policy vendor',
  workdir='<project-root>'
)
```

If the returned policy source says `fallback=strict`, use the unmapped-vendor
branch in step 4 before launching.

**Alternate endpoint**

Discover unauthenticated endpoints only after all four answers are known. Use
`SIXCAT_BASE_URL` first if set; otherwise probe common localhost bases. An
explicit user URL wins. Query `<base>/models`, keep its candidate IDs, and ask
the user to choose when there is more than one. Never use an exact model string
that is absent from the selected endpoint.

If `SIXCAT_API_KEY` is set, do not probe multiple bases. Require one explicit
`SIXCAT_BASE_URL` (or the URL the user just supplied) so the credential has one
known destination.

### 4. Preview settings before execution

Show a concise receipt before spending benchmark time:

- model ID;
- base URL (alternate) or Hermes provider/profile (runtime bridge);
- model identity source;
- model-card URL, mapping family, and exact temperature/top-p/top-k/min-p/seed;
- thinking setting and category token budgets;
- requested scope and 30-minute cap;
- code execution mode;
- policy fingerprint;
- parser version.

For **all** target types, run Sixcat's observe-only preflight before launch so
context and ETA diagnostics use the same contract. Alternate endpoint example:

```text
terminal(
  command='python -m sixcat preflight --base-url <url> --model <id> --policy <strict|vendor> <optional --policy-family family> --thinking <on|off> --limit <N> --json',
  workdir='<project-root>'
)
```

Hermes-runtime example (use the selected live route, not the normal agent API):

```text
terminal(
  command='python "${HERMES_SKILL_DIR}/scripts/hermes_runner.py" preflight --profile current --runtime-model <live-model> --runtime-provider <live-provider> -- --policy <strict|vendor> <optional --policy-family family> --thinking <on|off> --limit <N> --json',
  workdir='<project-root>'
)
```

Read `context`, `eta`, `policy`, and `policy_fingerprint` from the preflight
JSON. The Hermes proxy cannot attest the provider's upstream context limit;
missing context remains unknown, and this command is not an inference test. Show served context, source field, safe input budget, ETA range with
confidence, and warning codes. This is observe-only: it is not a score, it must
not set `--max-minutes`, and metadata failure must not abort the run. `--ctx N`
records an operator override as configured, not detected.

A request for internal `--policy vendor` that resolves to strict is a fallback,
not a vendor-recommended receipt. Never infer settings from model size or vendor
name when the catalog has no reviewed row.

If the user picked vendor or compare and preview shows no mapping, immediately
ask this option-only `clarify` (do not launch a fake vendor run):

```text
clarify(
  question='🏷️ No reviewed vendor row for this model ID. Use a listed family, enter your own settings, or stay on the deterministic baseline?',
  choices=[
    '🏷️ Adopt a reviewed vendor family — e.g. glm-5.x for a future GLM-5, without typing temps',
    '🎛️ Enter custom sampling — pick a preset temperature row',
    '🧊 Deterministic baseline — temperature 0'
  ]
)
```

If they adopt a family:

1. Run `python -m sixcat families --model <id> --json`.
2. Ask another `clarify` whose `choices` are the top 3 `suggested[].label`
   values plus `📂 Browse family groups`.
3. Browse groups with exactly these choices: `Qwen / Ornith`, `DeepSeek`,
   `GLM / Kimi`, `Other reviewed families`. Then page at most 4 family labels
   from `python -m sixcat families --group <qwen|deepseek|glm|other> --json`.
4. Launch with `--policy vendor --policy-family <family>`. The receipt source
   will say `adopted-for=<model>`; that is not an auto-detected mapping.

### 5. Show the exact run receipt before execution

Choose fresh paths under `results/hermes/`, including a sanitized model ID and a
timestamp. Restate the exact command, result path, journal path, detected model,
policy fingerprint, and timeout. Do not include an API key in command text or
artifacts.

For a new run, include `--no-resume`. Resume only when the user explicitly asks
and the endpoint model ID, policy fingerprint, budgets, code-execution mode, and prior journal all
match. Never silently resume across model-server sessions.

### 6. Start in the background

Check `process(action='list')` first. Do not launch a second Sixcat run against
the same endpoint unless the user explicitly accepts contention and invalid speed
receipts. Use `terminal` with `background=true` and `notify_on_complete=true`;
do not hide the process in an unmanaged shell:

```text
terminal(
  command='python -m sixcat --base-url <url> --model <id> --policy <policy> <scope> --out <result> --log <journal> --no-resume',
  workdir='<project-root>',
  background=true,
  notify_on_complete=true
)
```

For the current Hermes runtime model, use the runner instead. The command must
not contain an API key:

```text
terminal(
  command='python "${HERMES_SKILL_DIR}/scripts/hermes_runner.py" run --profile current --runtime-model <live-model> --runtime-provider <live-provider> -- --policy <policy> <scope> --out <result> --log <journal> --no-resume',
  workdir='<project-root>',
  background=true,
  notify_on_complete=true
)
```

The runner owns the temporary proxy, injects its random bearer token only
in-process, and shuts the proxy down on success, failure, timeout, or interrupt.
It verifies the effective provider/model route after every call and fails on any
fallback identity drift.

Record the returned process session ID. Immediately probe `/v1/models` again.
This identity guard must still return the same exact model ID; if it changed,
stop treating the run as valid and tell the user before any retry.

### 7. Give useful live status

Announce the start with model, policy, scope, process session ID, and receipt
paths. Use `process(action='poll')` for process output and the bundled helper for
journal truth:

```text
terminal(
  command='python "${HERMES_SKILL_DIR}/scripts/status.py" --log <journal> --result <result> --json',
  workdir='<project-root>'
)
```

Provide a live status at category transitions, on any truncation/loop warning,
when the user asks, and when the background completion notification arrives.
Report rows, pass/fail counts, latest item, truncations, failed loops, low
confidence parses, invalid completed journal lines, and elapsed row span. Do not
spam one message per item.

If the current surface supports proactive messages and the user asked for them,
send milestone updates to the current conversation only. Do not create a cron
job or message another channel without explicit approval. If proactive delivery
is unavailable, say that completion is automatic and `status` is available on
demand rather than claiming invisible live updates. Do not quote an ETA until
there is enough observed progress to label it as a rough projection.

If the user asks to stop, call `process(action='kill')`, preserve the JSONL, and
report the run as cancelled/incomplete. Never delete a partial receipt; offer a
verified resume only after the identity and policy checks in step 5 pass.

### 8. Verify and report

After process exit:

1. Confirm exit code zero with `process`.
2. Confirm the expected final JSON exists and load it with `read_file`.
3. Re-run preflight for an alternate endpoint. For a Hermes runtime target,
   confirm every request retained the exact profile/provider/model identity and
   that the tracked runner exited, which also closes its loopback proxy.
4. Report the labelled overall score, every category, row counts, policy source,
   policy fingerprint, budgets, parser version, code-execution mode, timeout state, truncations,
   loops, confidence flags, and wall TPS.
5. Report provider prefill/decode TPS only when the saved result contains it;
   missing split remains `n/a`.
6. For `both`, report vendor-minus-strict and preserve both artifact paths.

Missing tasks, unresolved infrastructure errors, identity drift, duplicate rows
or a failed probe prevent publication as a complete result. Normally completed
truncated or incorrectly answered items retain their first-response verdicts and
warnings; they do not make an otherwise complete 120-item run ineligible. Hidden
or unrevealed thinking traces are not a probe failure. Keep the files and flags.

If `timed_out` is true or `continuation.remaining` is nonzero, ask one
option-only `clarify`. For completed 120-item runs, offer Community Results
before optional failure-retry diagnostics; wrong answers do not block publication. Do not suggest a full
`--no-resume` rerun. Reuse the same `--out` and `--log`, omit `--no-resume`,
and add one `--retry` flag so the new rows merge into the existing receipt:

- **▶️ Continue remaining only (recommended after TIMEUP)** — `--retry remaining`
- **🔁 Retry failed only** — `--retry failed`; preserves all first-response headline
  verdicts and records a separate latest-attempt diagnostic. Unscored remaining items stay unscored.
- **🧩 Retry failed and remaining** — `--retry incomplete`
- **📁 Leave this receipt as-is**

Offer only the choices that apply. After that pass, report the immutable first-response overall
from the rewritten JSON and label `diagnostics.overall` separately as a latest-attempt diagnostic, never pass@1. Include `continuation.failed_rescored`.


### Public Community Results after completion

After reporting an eligible completed standard run, offer **Submit PR**, **Preview
submission**, and **Keep private** using one `clarify` with choices. Low scores
are eligible: wrong answers are not missing items. Do not ask a failure-retry
question instead merely because some scored answers were wrong. The complete
120-item first-response result, including all 20 locally executed Code items,
remains the default; never submit a reduced or incomplete run to the primary table.

Read `community/README.md`. Invoke `python -m sixcat submit <result> --preview`
with the known GitHub username and public runtime metadata. Fill model/source,
quantization, engine and wrapper from saved receipts and the known launch context;
ask only for genuinely missing source/identity, and use Unknown/Undisclosed for
unavailable backend details. Preserve exact model IDs and separate the evaluation
client/controller from the inference engine and API wrapper. Do not infer prices,
weights, hardware or engine versions.

Explain that the public PR contains model/configuration details, GitHub username
and the saved first answers. Dedicated reasoning fields are omitted by default;
inline text in saved answers is not rewritten. Preview the exported JSON, not the
raw local result with its endpoint/profile/path fields. Never publish a credential
or silently edit scored answers to redact them. `--include-reasoning` requires
explicit approval to include those additional fields.

Only after the user selects Submit PR (or explicitly requested publication with
the evaluation), call `python -m sixcat submit <result-or-export> --yes` with the
same metadata. `--yes` records consent to this publication; never supply it merely
because the user requested an evaluation. The deterministic helper creates a new
branch/fork when required and opens the PR; it does not merge it. Report its actual
URL. GitHub authentication is not a prerequisite to run the benchmark: when gh is
unavailable, retain an offline export and report the submission prerequisite.

Do not handwrite scores, README rows, or filenames. The helper generates a stable
MODEL__SOURCE__QUANT__USER__UTC__RUN-ID name, checks the approved benchmark manifest,
first-response totals, duplicate runs and README consistency. Keep original files
untouched. For non-interactive runs without explicit publication approval, save
an offline submission package/draft; do not block for input, read GitHub auth or
upload. Keep private means no publication and no repeated submission prompts.

## Additional Guardrails

- **Current model is the default target.** Ask first; never scan unrelated local
  ports before offering the exact model backing the calling Hermes session.
- **Follow-ups are immediate and option-only.** After the target answer, the next
  turn is a `clarify` with choices. Do not inspect first. Do not ask for a typed
  sampling template.
- **Hidden thinking is still thinking on.** Do not recommend Off because a cloud
  API omitted `reasoning_content` or `<think>` blocks.
- **Agent API is not raw inference.** Do not score the normal Hermes API server
  agent facade as if it were the underlying model. Use `hermes_runner.py`.
- **No silent provider fallback.** Hermes-runtime mode checks the actual route
  after every request and aborts on model/provider identity drift.
- **One endpoint can expose several models.** Ask which exact ID to use.
- **No silent parameter override.** Show resolved values before execution.
- **No secret leakage.** Do not print environment variables or credential files.
- **No invented speed split.** Wall TPS is universal; provider split is optional.
- **No stale-port scoring.** Identity guard before and after every run.
- **No destructive server control.** This skill never kills or rebinds a process.
- **No full rerun after TIMEUP.** Offer `--retry remaining|failed|incomplete` on
  the same journal so leftover or failed items merge into one receipt.
- **Preflight is not a score.** Context detection and probe-cost ETA are
  diagnostics. Do not award points from them or turn ETA into a suite fuse.

## Verification

The skill is working when:

- the target choice was asked before endpoint detection;
- the follow-up questions were asked immediately after the target answer, before
  inspect or preflight, and every question used selectable options;
- preflight returns `status=ready` for an alternate endpoint, or Hermes inspect
  returns one exact profile/model/provider plus a policy fingerprint;
- the user approved policy and scope after seeing exact sampling values;
- the background process is tracked by a Hermes process session ID;
- the JSONL live status is re-readable while the run is active;
- the final model identity matches preflight;
- the result JSON is self-auditing and all warnings are surfaced;
- a timed-out or incomplete run asked to merge remaining/failed items instead of
  suggesting a full rerun;
- one-line target requests bypassed the wizard and upgrade prompts; optional
  interactive release choices were offered only in the customization path;
- every `clarify` call, including follow-ups, included a non-empty `choices`
  array so Telegram rendered buttons instead of a bare question;
- an unmapped vendor request offered adopt-family, custom, or strict instead of
  launching a fake vendor run.


## Operator vocabulary preserved for conversational clarity

Keep these plain-English explanations available in the skill UI and do not replace them with a fill-in template.

- 🧠 Current Hermes session model (recommended) — use the exact live raw model, not the agent facade.
- 👤 Another Hermes profile — resolve that profile first.
- 🔌 Alternate OpenAI-compatible endpoint — detect the endpoint only after the target choice.
- 🎛️ Custom sampling — temperature controls randomness; top-p, top-k, and min-p filter the candidate distribution.
- 🧊 Deterministic baseline — temperature 0.
- 🏷️ Vendor-recommended temperature/settings — reviewed model-family settings when mapped.
- 🔬 Standard inspection — 20 scored items per category, about 120 scored rows total.
- ⚖️ Compare both — strict and vendor profiles remain separate receipts.
- ⚡ Quick — reduced per-category scope.
- 🧭 Full — all shipped rows, still time-bounded unless explicitly uncapped.
- 🛠️ HumanEval host-guarded execution — default local execution of all 20 Code items.
- 🧪 Standard benchmark — the short daily-driver run.
- 🛡️ `--skip-code-exec` — opt out of Code only when explicitly requested by the user.
- 🚫 Generated code execution is not a security sandbox.
- 🌡️ Thinking controls whether the model's reasoning mode is requested.
- 5️⃣ Five items per category and 🔟 ten items per category are small custom scopes.
- ♾️ Full mode with `--max-minutes 0` is intentionally uncapped.

Seed helps repeat stochastic settings when the endpoint honors it; some endpoints ignore it. Use selectable options for setup questions. Do not use a fill-in template for sampling values.
