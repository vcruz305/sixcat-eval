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
repair generated answers or let the controller grade itself. Follow the skill's
code-isolation and incomplete-result rules. These are evaluation-operation rules,
not a prohibition on source inspection for explicitly requested development work.
