"""Small, deterministic CI policy check: read-only token, immutable actions."""
from __future__ import annotations
import re
from pathlib import Path
import yaml


def validate(root: Path) -> list[str]:
    errors = []
    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        # BaseLoader leaves GitHub's 'on' key as text (YAML 1.1 otherwise treats it as Boolean).
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        if not isinstance(document, dict):
            errors.append(f"{path}: workflow must be a mapping")
            continue
        events = document.get("on") or {}
        if "pull_request_target" in events:
            errors.append(f"{path}: privileged pull_request_target is not allowed")
        if document.get("permissions") != {"contents": "read"}:
            errors.append(f"{path}: default token must be contents: read only")
        for name, job in (document.get("jobs") or {}).items():
            if "permissions" in job and job["permissions"] != {"contents": "read"}:
                errors.append(f"{path}/{name}: job must not escalate token permissions")
            timeout = job.get("timeout-minutes", "")
            if not timeout.isdigit() or not 1 <= int(timeout) <= 30:
                errors.append(f"{path}/{name}: bounded job timeout is required")
            for step in job.get("steps") or []:
                action = step.get("uses")
                if action and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[a-f0-9]{40}", action):
                    errors.append(f"{path}/{name}: action is not pinned to a full commit SHA: {action}")
                if action and action.startswith("actions/checkout@") and (step.get("with") or {}).get("persist-credentials") != "false":
                    errors.append(f"{path}/{name}: checkout must not persist credentials")
                if "${{ github.event." in step.get("run", ""):
                    errors.append(f"{path}/{name}: event text must not be interpolated directly into shell code")
    return errors


if __name__ == "__main__":
    import sys
    errors = validate(Path(__file__).resolve().parents[1])
    print("\n".join(errors) if errors else "Workflow security policy passed")
    sys.exit(bool(errors))
