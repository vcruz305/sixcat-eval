# Community Results (unreleased on main)

One complete standard run, one explicitly approved public JSON, one generated
README entry. No evaluation rerun is needed to contribute. The main table is
**community-reported: format and arithmetic consistency checked**, not a claim
that Sixcat verified the contributor's model weights or reproduced the run.

## After an evaluation

Hermes reports the result and asks **Submit PR / Preview submission / Keep
private** for every eligible completed 120-item run, including low scores.
Agreeing to submit authorizes sharing the public JSON, creating a submission
branch (and a contributor fork when needed), and opening a PR. It never merges
the score PR. The original result JSON and journal stay where they are.

The regular CLI offers the same question when attached to a terminal. A
non-interactive invocation prepares a local `.submission` draft/package instead;
it never reads GitHub authentication, waits for input, or uploads automatically.
`SIXCAT_NO_SUBMISSION_PROMPT=1` suppresses this post-run hook. It does not disable
manual export or submission. Hermes handles its own conversational confirmation.
GitHub login is not required to evaluate a model.

## Commands

```bash
# Offline: inspect the exact public copy. Existing route hints fill known values.
python -m sixcat submit results/model.json --preview --github-user YOUR_USERNAME

# Offline: prepare JSON and a README-row preview. Fill only missing metadata.
python -m sixcat submit results/model.json --export-dir results/submission \
  --github-user YOUR_USERNAME --source-kind local --source local \
  --quant-format EXL3 --quant-precision 3.05bpw \
  --inference-engine ExLlamaV3 --engine-version YOUR_VERSION \
  --api-wrapper TabbyAPI --wrapper-version YOUR_VERSION

# Publish only after reviewing/approving these public fields and saved answers.
python -m sixcat submit results/submission/EXPORTED_FILE.json --yes

# Regenerate/check the managed README block in a checkout.
python -m sixcat community render --root .
python -m sixcat community validate --root .
```

`--yes` is explicit publication consent, not permission to change model settings,
run inference, merge a PR or publish a release. Without it an interactive submit
command asks; a non-interactive command only exports. `--preview` does not write
files or call GitHub. Metadata can also be passed in a JSON object with
`--metadata metadata.json`. Preview/export can report `needs_metadata`; only
source-kind, source and the contributor need resolution. Unknown cloud backend
quantization/engine details remain **Undisclosed**; other missing details remain
**Unknown**. No price restriction is introduced.

Use the existing authenticated `gh` CLI to publish. An authenticated username
must match the contributor. Users without repository write access use their own
fork. No token is copied into argv, the export, the README or the PR. If gh is
missing, authenticate it separately and resubmit the already-prepared local
export. A partially created branch is retained on error, never overwritten.

## Public metadata and naming

The JSON records exact model ID plus readable name, public model/quant links and
revisions, cloud/local source, quant format and precision, quant method, inference
engine/version, API wrapper/version, evaluation client, optional hardware,
context, weight size and average bpw. Public runtime hints from the Hermes bridge
separate the provider from the controller. Contributor overrides are labeled
contributor-reported, not engine autodetection or weight attestation.

The canonical repository path is:

```text
community/results/YYYY/MM/MODEL__SOURCE__QUANT__GITHUB-USER__UTC-TIMESTAMP__RUN-ID.json
```

Names use bounded lowercase slugs; double underscores separate fields. Common
source abbreviations include `nous`, `or` and `local`. The short hash is backed
by a full run ID in the JSON. The exact ID is inside the JSON, not reconstructed
from the filename. Run identity excludes contributor/export metadata and optional
reasoning so renaming or changing the username cannot duplicate the same run.
Separate genuine runs keep their own execution-segment identities. No best-only
filter selects a contributor's highest score. Ordering is chronological within
benchmark/policy/thinking groups, not a misleading universal ranking.

## Privacy and evidence

The public JSON is an allowlisted export with schema `sixcat-community-v1`.
It includes exact saved first answers, item verdicts, scores/counts, task keys,
policy/budgets, the approved benchmark manifest, and available timing/token
telemetry. It excludes private endpoints, local paths/profile names, server
properties, wire prompts, grader internals and latest-attempt diagnostic answers.
The source file is neither renamed nor rewritten. Its SHA-256 and the public
content hash are included for integrity, not authentication.

Dedicated `reasoning_content` fields are omitted unless `--include-reasoning` is
explicitly selected. **Inline reasoning already in raw answer text is preserved**:
answers are never silently rewritten to hide text. Preview the actual export.
A best-effort scan blocks recognizable credentials in retained text; it is not a
perfect secret detector. Suspicious text requires local review, not silent
redaction followed by a claim that the answer is original.

## Validation and review

The primary table requires exactly the frozen 120 standard tasks, 20 per
category, Code executed locally, successful policy probe, complete counts, and
consistent first-response scores. Wrong answers count normally. A normally
completed truncated answer keeps its outcome/flag; missing responses or unresolved
infrastructure errors cannot become a complete submission. Code-disabled, full
884-item, smaller-screen, and agent-assisted stdio results have different scopes.

The schema and validator reject unknown fields, malformed/non-finite numbers,
duplicate JSON keys, duplicate task keys, wrong counts/totals, altered policy
fingerprints, unknown benchmark manifests, duplicate runs, unsafe paths and
mismatched table rows. Strict/vendor/custom and thinking on/off are grouped by
full policy and benchmark identity, not silently pooled.

Maintainers own `sixcat/community-compatibility.json`. A result cannot approve
its own modified benchmark. The PR-validation workflow loads validator code and
the registry from the trusted base checkout, reads the candidate as data, and
**never executes submitted Python answers**. Code still runs locally during the
original 120-item evaluation. All workflow tokens remain read-only.

A result PR may only add one canonical JSON and update the managed README block;
existing public results are append-only. Updates outside the block, arbitrary
files, multiple result additions, author mismatch and result removal/modification
fail scope validation. Maintainer software changes without new results are
separate development PRs. At initial workflow bootstrap, no score submissions are
accepted until the trusted validator exists on main.

Concurrent README edits can conflict. Update the contribution branch from main,
then run `sixcat community render` to reconstruct the table from all approved
JSONs. Never resolve a conflict by dropping another contributor's entry or editing
scores by hand. Duplicate submissions return the existing result/PR where known.
