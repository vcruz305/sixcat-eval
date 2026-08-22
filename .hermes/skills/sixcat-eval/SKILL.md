---
name: sixcat-eval
description: Run Sixcat conversationally with verified live receipts.
version: 0.4.2
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

Completion criterion: target kind is explicit. Do not inspect, preflight, or
preview yet. The next assistant turn must be the follow-up `clarify` call.

### 2. Immediately ask the remaining questions

After the target answer, ask the follow-up `clarify` in the same turn you
acknowledge it. Do not run `inspect`, `preflight`, `terminal`, or any other
tool first. Do not write a long policy preview first. Every question, including
dependent follow-ups, must use `clarify` with selectable options. Never ask the
user to type a free-form sampling string, size, profile name, or URL as the
only input.

If the target is **another Hermes profile**, immediately offer up to four live
profile names as choices (plus Other). If it is **an alternate endpoint**,
immediately offer the common loopback candidates as choices (plus Other):

- `http://127.0.0.1:8085/v1`
- `http://127.0.0.1:8083/v1`
- `http://127.0.0.1:8000/v1`
- `http://127.0.0.1:30000/v1`

Then immediately send one batched `clarify` form with four independently
answerable questions. Prefix every question and every choice with the distinct
emoji shown below. Always offer the four sampling choices now; do not wait to
learn whether a reviewed mapping exists.

#### A. 🎛️ How should the model sample answers?

- **🏷️ Vendor-recommended temperature/settings (recommended)** — use the
  reviewed model-card temperature and token filters; Sixcat uses seed `1` so
  repeated runs are easier to compare. Thinking is selected separately below.
  If preview later shows no reviewed mapping, do not launch a fake vendor run.
- **🔬 Compare baseline vs vendor settings** — run the deterministic baseline
  first, then the vendor-recommended settings, with separate receipts and a delta.
- **🧊 Deterministic temperature baseline** — temperature `0` and no seed unless
  the user explicitly supplies one. Thinking is selected separately below.
- **🎛️ Custom sampling** — choose one of the preset sampling rows below.

If Custom is selected, immediately ask one follow-up `clarify` with options.
Do not use a fill-in template:

- **🌡️ temperature=0.7, no filters (recommended custom)** — `--policy custom --temperature 0.7`
- **🏷️ temperature=1.0, top_p=0.95** — GLM-5.x / many thinking-model cards
- **🎯 temperature=0.6, top_p=0.95, top_k=20, min_p=0** — Qwen3-style thinking
- **🧊 temperature=0.0, no filters** — greedy custom

Restate the resolved flags before execution.

#### B. 📏 How large should the evaluation be?

- **⚖️ Standard (recommended)** — **20 scored items per category**, **about 120
  scored rows total**, with a 30-minute wall-clock safety cap.
- **⚡ Quick smoke** — 3 scored items per category, about 18 total, with a
  10-minute cap; useful for checking plumbing, not ranking models.
- **🧭 Full battery** — every shipped row (`--full --max-minutes 0`); warn that it
  can exceed an hour and cost substantially more on hosted models.
- **🛠️ Custom size** — choose one of the preset size rows below.

If Custom size is selected, immediately ask one follow-up `clarify` with options:

- **5️⃣ 5 per category, 15 minutes**
- **🔟 10 per category, 20 minutes**
- **4️⃣0️⃣ 40 per category, 60 minutes**
- **♾️ 20 per category, no wall cap**

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

- **🧠 Thinking on (recommended when supported)** — request the model's reasoning
  mode and automatically raise category token budgets. Recommend this for
  reasoning-capable models, including cloud APIs that hide thinking token
  blocks. Hidden or unrevealed traces are not a reason to turn thinking off.
- **⚡ Thinking off** — faster, cheaper baseline. Do not choose this just because
  the provider does not return `reasoning_content` or `<think>` blocks.

Choose **On** by default unless the user picked Off. Sixcat's pre-run probe
auto-detects visible, hidden, or unrevealed thinking and still continues when
On was selected. It only fail-closes Thinking Off if a visible reasoning trace
leaks. Map the choice to `--thinking on|off` for every sampling mode, including
strict, vendor-recommended, compare, and custom.

Completion criterion: exact sampling values, explicit thinking choice,
per-category item cap/full mode, wall cap, and code-execution mode are explicit.
All of those answers came from option rows, not a typed template.

### 3. Detect the endpoint and model

Only after the questions are answered, run the bundled preflight through
`terminal` from the project root:

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

### 4. Preview what will run

After the questions are answered and the target is resolved, show the exact
target, the resolved settings, and a plain-English explanation. Never show only
internal words like `vendor`, `strict`, or `seed` and expect the user to know
what they mean:

- **Temperature controls randomness**: `0` is the most repeatable; higher values
  allow more varied answers.
- **Top-p, top-k, and min-p filter** which next-token choices remain available.
  `none` means Sixcat does not send that control.
- **Thinking controls whether** the endpoint is asked to use reasoning mode.
  Hidden or unrevealed thinking token blocks still count as thinking on.
- **Seed helps repeat** the same sampling path when the endpoint supports seeds;
  **some endpoints ignore it**, so it is not a universal reproducibility promise.
- Show category token budgets, cited settings source, policy fingerprint, and every
  fallback or ambiguity warning.

A request for internal `--policy vendor` that resolves to strict is a fallback,
not a vendor-recommended receipt. Never infer settings from model size or vendor
name when the catalog has no reviewed row. If the user picked vendor or compare
and preview shows that fallback, ask with options whether to continue as custom
or strict instead of launching a fake vendor run.

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
rows, or a failed probe request is incomplete or non-comparable. Hidden or
unrevealed thinking traces are not a probe failure. Keep the files and label
the failure honestly.

If `timed_out` is true or `continuation.remaining` / `continuation.failed` is
nonzero, immediately ask one option-only `clarify`. Do not suggest a full
`--no-resume` rerun. Reuse the same `--out` and `--log`, omit `--no-resume`,
and add one `--retry` flag so the new rows merge into the existing receipt:

- **▶️ Continue remaining only (recommended after TIMEUP)** — `--retry remaining`
- **🔁 Retry failed only** — `--retry failed`; keeps PASS rows and replaces FAIL
  rows. Unscored remaining items stay unscored.
- **🧩 Retry failed and remaining** — `--retry incomplete`
- **📁 Leave this receipt as-is**

Offer only the choices that apply. After that pass, report the merged overall
from the rewritten JSON, including `continuation.failed_rescored`.

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
  suggesting a full rerun.
