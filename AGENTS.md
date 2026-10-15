# Sixcat operator entry point

For a request to run a model evaluation, read the README's **Just ask your agent**
section and `.hermes/skills/sixcat-eval/SKILL.md` before launching anything.
A provider and model name are sufficient user input; the skill owns the defaults,
authentication reuse, model discovery, unique output names, execution and reporting.
Do not ask the user to copy a long operator prompt or fill optional settings.

For example: "Run sixcat eval against the Hermes provider nous portal and the
model Nemotron ultra free." Resolve the actual name through the fresh authenticated
catalog; preserve the free requirement and never guess or substitute a paid route.
The optional interactive wizard is not the default for a named target.

When operating an evaluation, do not put answer keys into any model context,
repair generated answers or let the controller grade itself. Follow the skill's
code-isolation and incomplete-result rules. These are evaluation-operation rules,
not a prohibition on source inspection for explicitly requested development work.
