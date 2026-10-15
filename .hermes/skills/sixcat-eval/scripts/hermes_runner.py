"""Compatibility entry point for the project-local Hermes skill."""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Prefer an explicitly chosen checkout, then the caller's checkout, then this
# skill's source tree. An installed wheel works from any other directory.
candidates = []
if os.environ.get("SIXCAT_PROJECT_ROOT"):
    candidates.append(Path(os.environ["SIXCAT_PROJECT_ROOT"]).expanduser())
candidates.extend((Path.cwd(), *Path.cwd().parents, *Path(__file__).resolve().parents))
for root in candidates:
    if (root / "sixcat" / "hermes.py").is_file():
        sys.path.insert(0, str(root))
        break

from sixcat import hermes as _runner

def __getattr__(name):
    return getattr(_runner, name)

if __name__ == "__main__":
    raise SystemExit(_runner.main())
