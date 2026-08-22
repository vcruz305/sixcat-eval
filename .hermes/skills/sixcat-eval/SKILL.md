---
name: sixcat-eval
description: Run Sixcat conversationally with verified live receipts.
version: 0.1.0
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

Run Sixcat against an already-running OpenAI-compatible model server. Detect the
served model, preview the exact reviewed sampling policy, ask the user how large
a run they want, keep the run observable, and report only from saved receipts.

## When to Use

- The user asks Hermes to test, benchmark, compare, or score a model with Sixcat.
- The user invokes `/sixcat-eval` inside this repository.
- The user asks for live status from an existing Sixcat JSONL journal.

Do not use this skill to launch, kill, swap, download, or quantize a model.
Do not start, stop, or replace any model server; evaluate the endpoint already
selected by the user. If no endpoint is reachable, report that prerequisite.

## Prerequisites

- Start Hermes inside the Sixcat git checkout.
- Trust its project skills once with `hermes skills trust` from the project root.
- Python 3.11+ and the repository dependencies must be available.
- The target server must expose `/v1/models` and `/v1/chat/completions`.
- For an authenticated endpoint, keep the key in `SIXCAT_API_KEY`; never print it.
- An API key requires exactly one explicit `SIXCAT_BASE_URL` or `--base-url`; the
  preflight refuses to broadcast one credential across discovery candidates.
- Without a credential, optional `SIXCAT_BASE_URL` can select the endpoint without
  putting it in chat; otherwise discovery probes common localhost ports unauthenticated.

## Quick Reference

- Default Sixcat run: `--limit 20 --max-minutes 30`.
- Current scorer/parser identity: `v3`; older `v2` receipts are non-comparable.
- Vendor default seed: `1`; omit `--seed` unless the user requests an override.
- New run: use `--no-resume` and a fresh artifact basename.
- Live status: summarize the JSONL with the bundled status helper.
- Completion: require a final JSON result plus a zero process exit code.

## Procedure

### 1. Detect the endpoint and model

Run the bundled preflight through `terminal` from the project root:

```text
terminal(
  command='python "${HERMES_SKILL_DIR}/scripts/preflight.py" --json',
  workdir='<project-root>'
)
```

If the user named an endpoint or model, pass `--base-url <url>` and an exact
`--model <id>`. The helper checks `/v1/models`; it does not trust a filename,
Hermes chat-model label, old journal, or user-facing server nickname.

If `SIXCAT_API_KEY` is set, require one explicit endpoint before preflight. Never
send that credential while scanning the default candidate list.

If multiple endpoints or models are found, use `clarify` when available and ask
the user to choose. Never pick the first one silently. Completion criterion:
one base URL and one exact model ID are selected.

### 2. Preview what will run

Before asking for run size, show:

- exact endpoint and detected model ID;
- recommended policy (`vendor` when a reviewed family matches, otherwise `strict`);
- temperature, top-p, top-k, min-p, thinking state, seed, and category budgets;
- cited policy source and policy fingerprint;
- every fallback or ambiguity warning.

A request for `vendor` that resolves to `strict` is a fallback, not a vendor
receipt. Say so plainly. Never infer a temperature from model size or vendor
name when the catalog has no verified row.

### 3. Ask policy and run size

After detection, ask the user to choose the policy. Recommend the resolved
vendor policy first when it exists:

- **Vendor**: reviewed model-card settings and seed 1.
- **Both**: strict first, then vendor, separate journals/results and a delta.
- **Strict**: temperature 0, thinking off.

Then ask for one run scope. Put the default first:

- **Standard**: `--limit 20 --max-minutes 30` (recommended default).
- **Quick**: `--limit 3 --max-minutes 10` for a plumbing smoke.
- **Full**: `--full --max-minutes 0`; warn that it can exceed an hour.
- **Custom**: ask for both item limit and wall-clock minutes. `0` minutes means no cap.

Also ask how to handle HumanEval:

- **Host-guarded** (recommended default): short-lived host subprocess with `-I -S`,
  sanitized environment, temp working directory, timeout, AST escape checks,
  restricted builtins/imports, and a harness-owned randomized success receipt.
  State clearly that this is low overhead but **not a security sandbox**.
- **Skip Code**: add `--skip-code-exec`; Code is `n/a` and the overall is visibly
  flagged `code-exec-disabled`.

Use one batched `clarify` form when all three questions are independent. If Custom is
chosen, ask its numeric follow-up separately. Completion criterion: policy,
limit/full mode, time cap, and code-execution mode are explicit.

### 4. Show the exact run receipt before execution

Choose fresh paths under `results/hermes/`, including a sanitized model ID and a
timestamp. Restate the exact command, result path, journal path, detected model,
policy fingerprint, and timeout. Do not include an API key in command text or
artifacts.

For a new run, include `--no-resume`. Resume only when the user explicitly asks
and the endpoint model ID, policy fingerprint, budgets, code-execution mode, and prior journal all
match. Never silently resume across model-server sessions.

### 5. Start in the background

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

Record the returned process session ID. Immediately probe `/v1/models` again.
This identity guard must still return the same exact model ID; if it changed,
stop treating the run as valid and tell the user before any retry.

### 6. Give useful live status

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
verified resume only after the identity and policy checks in step 4 pass.

### 7. Verify and report

After process exit:

1. Confirm exit code zero with `process`.
2. Confirm the expected final JSON exists and load it with `read_file`.
3. Re-run preflight and confirm the endpoint still serves the same model ID.
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

- **Chat model is not target model.** Hermes may be reasoning with a cloud model
  while Sixcat targets a local server. `/v1/models` is the target identity.
- **One endpoint can expose several models.** Ask which exact ID to use.
- **No silent parameter override.** Show resolved values before execution.
- **No secret leakage.** Do not print environment variables or credential files.
- **No invented speed split.** Wall TPS is universal; provider split is optional.
- **No stale-port scoring.** Identity guard before and after every run.
- **No destructive server control.** This skill never kills or rebinds a process.

## Verification

The skill is working when:

- preflight returns `status=ready` with one endpoint, one model, and a policy fingerprint;
- the user approved policy and scope after seeing exact sampling values;
- the background process is tracked by a Hermes process session ID;
- the JSONL live status is re-readable while the run is active;
- the final model identity matches preflight;
- the result JSON is self-auditing and all warnings are surfaced.
