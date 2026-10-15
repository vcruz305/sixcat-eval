# Sixcat operator entry point

For a request to run a model evaluation, read the README's **Just ask your agent**
section and `.hermes/skills/sixcat-eval/SKILL.md` before launching anything.
A provider and model name are sufficient user input; the skill owns the defaults,
authentication reuse, model discovery, unique output names, execution and reporting.
Do not ask the user to copy a long operator prompt or fill optional settings.

For example: "Run sixcat eval against the Hermes provider nous portal and the
model Nemotron ultra free." Resolve the actual name through the fresh authenticated
catalog. This is only an example model name, not a free-only requirement.
No price filter by default: paid, free and subscription-backed targets are allowed.
Preserve the requested model/variant, including words such as "free" in its name.
Use `--free-only` only for a separate explicit price restriction, never inferred
from the example or model name. Never guess or silently substitute another route.
The optional interactive wizard is not the default for a named target.

When operating an evaluation, do not put answer keys into any model context,
repair generated answers or let the controller grade itself.
**Code execution is enabled by default.** Run all 120 items across all six
categories, including the 20 HumanEval Code items, and execute/test their Python
locally with the existing checker. Do not require a container, VM or separate
isolation approval. Never add `--skip-code-exec` or substitute Code N/A unless
the user explicitly requests skipping Code. Preserve the existing guards and
report genuine execution errors or incomplete counts without changing scope.
These are evaluation-operation rules,
not a prohibition on source inspection for explicitly requested development work.

After a completed standard 120-item run, follow the skill Community Results
section: offer Submit PR / Preview submission / Keep private. Low scores are
eligible. Only explicit publication approval authorizes `sixcat submit --yes`.
Use the deterministic exporter/PR helper; no handwritten scores, no raw private
JSON uploads, no automatic merge, and no release creation. See community/README.md.
