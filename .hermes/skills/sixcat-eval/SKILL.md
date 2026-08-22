---
name: sixcat-eval
description: Run Sixcat conversationally with verified live receipts.
version: 0.4.0
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
an alternate OpenAI-compatible endpoint. Ask for the target first, preview the
exact reviewed sampling policy, keep the run observable, and report only from
saved receipts.

## When to Use

- The user asks Hermes to test, benchmark, compare, or score a model with Sixcat.
- The user invokes `/sixcat-eval` inside this repository.
- The user asks for live status from an existing Sixcat JSONL journal.

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
- Current scorer/parser identity: `v4`; older `v2`/`v3` receipts are readable
  but non-comparable to new challenge-selection/tool-grader runs.
- Vendor-recommended temperature/settings use seed `1` for repeatability when a
  reviewed model mapping exists. Custom mode may use any integer or no seed.
- New run: use `--no-resume` and a fresh artifact basename.
- Live status: summarize the JSONL with the bundled status helper.
- Completion: require a final JSON result plus a zero process exit code.

## Procedure

### 1. Ask which target to evaluate

Before probing any endpoint, ask exactly:

> 🎯 Do you want to run Sixcat against the model I am currently running,
> another Hermes profile, or an alternate OpenAI-compatible endpoint?

Use one `clarify` question. Each choice must include its mini-explainer:

1. **🧠 Current Hermes session model (recommended)** — evaluate the exact model
   and provider powering this conversation through the clean raw-model bridge;
   do not include this agent's persona, tools, memory, or conversation.
2. **👤 Another Hermes profile** — evaluate that profile's configured default
   model using the authentication already stored for that profile.
3. **🔌 Alternate OpenAI-compatible endpoint** — evaluate an already-running
   `/v1/chat/completions` server selected through its `/v1/models` identity.

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
the runner resolves that profile's configured model/provider.

Hermes' normal API server is an **agent facade**: it adds the profile prompt,
tools, memory, and agent loop, and its `/v1/models` entry is a profile alias.
That is useful for apps but is not a raw model benchmark. The bundled runner
instead uses Hermes' provider/auth resolver and a temporary authenticated
loopback proxy to call the exact raw model with Sixcat's sampling parameters.

Completion criterion: target kind, profile when applicable, exact model, and
exact provider are explicit before policy/scope questions.

### 2. Detect the endpoint and model

Run the bundled preflight through `terminal` from the project root:

```text
terminal(
  command='python "${HERMES_SKILL_DIR}/scripts/preflight.py" --json',
  workdir='<project-root>'
)
```

For **Alternate OpenAI-compatible endpoint**, run the bundled preflight. If the
user named an endpoint or model, pass `--base-url <url>` and an exact
`--model <id>`. The helper checks `/v1/models`; it does not trust a filename,
old journal, or user-facing server nickname.

If `SIXCAT_API_KEY` is set, require one explicit endpoint before preflight. Never
send that credential while scanning the default candidate list.

If multiple endpoints or models are found, use `clarify` when available and ask
the user to choose. Never pick the first one silently. Completion criterion:
one base URL and one exact model ID are selected.

For a Hermes runtime target, the `inspect` receipt replaces endpoint discovery.
It must say `target_kind=hermes_runtime_model`, show the exact profile/model/
provider, report `auth=resolved`, and state that the agent facade is bypassed.

### 3. Preview what will run

Before asking for run size, show the exact target, the resolved settings, and a
plain-English explanation. Never show only internal words like `vendor`,
`strict`, or `seed` and expect the user to know what they mean:

- **Temperature controls randomness**: `0` is the most repeatable; higher values
  allow more varied answers.
- **Top-p, top-k, and min-p filter** which next-token choices remain available.
  `none` means Sixcat does not send that control.
- **Thinking controls whether** the endpoint is asked to expose a reasoning trace.
- **Seed helps repeat** the same sampling path when the endpoint supports seeds;
  **some endpoints ignore it**, so it is not a universal reproducibility promise.
- Show category token budgets, cited settings source, policy fingerprint, and every
  fallback or ambiguity warning.

A request for internal `--policy vendor` that resolves to strict is a fallback,
not a vendor-recommended receipt. Never infer settings from model size or vendor
name when the catalog has no reviewed row.

### 4. Ask sampling setup, run size, code handling, and thinking

Use one batched `clarify` form with four independently answerable questions.
Prefix every question and every choice with the distinct emoji shown below.

#### A. 🎛️ How should the model sample answers?

When a reviewed mapping exists, offer:

- **🏷️ Vendor-recommended temperature/settings (recommended)** — use the
  reviewed model-card temperature and token filters; Sixcat uses seed `1` so
  repeated runs are easier to compare. Thinking is selected separately below.
- **🔬 Compare baseline vs vendor settings** — run the deterministic baseline
  first, then the vendor-recommended settings, with separate receipts and a delta.
- **🧊 Deterministic temperature baseline** — temperature `0` and no seed unless
  the user explicitly supplies one. Thinking is selected separately below.
- **🎛️ Custom sampling** — the user chooses temperature and any optional controls.

For an **unknown or stealth model**, there is no trustworthy model-card mapping.
Offer **🎛️ Custom sampling** first as the recommendation, followed by
**🧊 Deterministic baseline**. **Do not offer Both when no reviewed vendor mapping exists**;
running strict twice with a different seed is not a meaningful comparison.

If Custom is selected, ask one open-ended follow-up using this fill-in template:

```text
temperature=0.7, top_p=none, top_k=none, min_p=none, seed=none
```

Explain that only `temperature` is required. Parse `none` as an omitted control
and map the values to `--policy custom --temperature ...` plus optional
`--top-p`, `--top-k`, `--min-p`, and `--seed` flags. Restate
all resolved values before execution.

#### B. 📏 How large should the evaluation be?

- **⚖️ Standard (recommended)** — **20 scored items per category**, **about 120
  scored rows total**, with a 30-minute wall-clock safety cap.
- **⚡ Quick smoke** — 3 scored items per category, about 18 total, with a
  10-minute cap; useful for checking plumbing, not ranking models.
- **🧭 Full battery** — every shipped row (`--full --max-minutes 0`); warn that it
  can exceed an hour and cost substantially more on hosted models.
- **🛠️ Custom size** — ask for items **per category** and wall-clock minutes.
  `0` minutes means no cap. The cap stops new rows but preserves partial receipts.

The `--limit` value is always per category. Knowledge may draw from MMLU, ARC,
HellaSwag, and WinoGrande, but those sources share the category cap; `--limit 20`
must never become 80 Knowledge rows.

Limited runs use frozen `challenge-v1` selection, not file prefixes: Quick starts
with the hardest few items and Standard uses a hard/diverse 20. Code difficulty
uses an independent 49-model HumanEval ranking; Full runs all 164 HumanEval tasks.
Tools grade exact arguments, call count/order, multi-call requests, distractors,
and abstention. Every receipt includes the selection profile and fingerprint;
Full preserves the complete source corpus.

#### C. 🧪 Should Sixcat execute generated HumanEval code?

- **🛡️ Host-guarded HumanEval (recommended)** — execute generated Python in a
  short-lived subprocess with `-I -S`, sanitized environment, temp directory,
  timeout, AST escape checks, restricted builtins/imports, and a harness-owned
  success receipt. This is low overhead but **not a security sandbox**.
- **🚫 Skip generated-code execution** — add `--skip-code-exec`; Code becomes
  `n/a` and the overall is visibly flagged `code-exec-disabled`.

#### D. 🧠 Should reasoning/thinking be enabled?

- **🧠 Thinking on (recommended when supported)** — lets a reasoning model use
  its reasoning mode and automatically raises category token budgets. This is
  the default recommendation for capable reasoning models because it measures
  their stronger intended mode, but it can be slower and cost more.
- **⚡ Thinking off** — faster, cheaper, and more broadly compatible; use it for
  a latency-oriented baseline or when the endpoint cannot return a reasoning
  trace.

Choose **On** by default unless the inspected model/provider is known not to
support reasoning traces. Sixcat's pre-run policy probe must fail closed before
scoring if On was selected but the endpoint does not actually expose reasoning.
Map the choice to `--thinking on|off` for every sampling mode, including strict,
vendor-recommended, compare, and custom.

If Custom sampling or Custom size is selected, ask its dependent follow-up only
after the batch. Completion criterion: exact sampling values, explicit thinking
choice, per-category item cap/full mode, wall cap, and code-execution mode are explicit.

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
  command='python -m sixcat --base-url <url> --model <id> --policy <policy> <scope> <optional --skip-code-exec> --out <result> --log <journal> --no-resume',
  workdir='<project-root>',
  background=true,
  notify_on_complete=true
)
```

For the current Hermes runtime model, use the runner instead. The command must
not contain an API key:

```text
terminal(
  command='python "${HERMES_SKILL_DIR}/scripts/hermes_runner.py" run --profile current --runtime-model <live-model> --runtime-provider <live-provider> -- --policy <policy> <scope> <optional --skip-code-exec> --out <result> --log <journal> --no-resume',
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

A run with timeout, truncation, missing confidence, identity drift, duplicate
rows, or policy-probe failure is incomplete or non-comparable. Keep the files,
label the failure honestly, and ask before rerunning.

## Additional Guardrails

- **Current model is the default target.** Ask first; never scan unrelated local
  ports before offering the exact model backing the calling Hermes session.
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

## Verification

The skill is working when:

- the target choice was asked before endpoint detection;
- preflight returns `status=ready` for an alternate endpoint, or Hermes inspect
  returns one exact profile/model/provider plus a policy fingerprint;
- the user approved policy and scope after seeing exact sampling values;
- the background process is tracked by a Hermes process session ID;
- the JSONL live status is re-readable while the run is active;
- the final model identity matches preflight;
- the result JSON is self-auditing and all warnings are surfaced.
