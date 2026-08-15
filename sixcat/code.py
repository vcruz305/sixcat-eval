from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .dataio import read_jsonl, take


def _run_humaneval(prompt: str, completion: str, test: str, entry: str, timeout: float = 8.0) -> bool:
    # strip markdown fences
    body = completion
    m = re.search(r"```(?:python)?\s*([\s\S]*?)```", completion)
    if m:
        body = m.group(1)
    # if model repeated the prompt, keep from first def
    if "def " in body:
        body = body[body.find("def ") :]
    src = prompt + body + "\n" + test + f"\ncheck({entry})\n"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sol.py"
        p.write_text(src, encoding="utf-8")
        try:
            r = subprocess.run(
                [sys.executable, str(p)],
                capture_output=True,
                timeout=timeout,
                text=True,
            )
        except subprocess.TimeoutExpired:
            return False
        return r.returncode == 0


def run_code(client, limit: int | None) -> list[dict]:
    rows = []
    for item in take(read_jsonl("humaneval.jsonl"), 20 if limit is None else min(limit, 20)):
        prompt = item["prompt"]
        out = client.complete(
            "Complete the following Python function. Output only code.\n\n" + prompt,
            max_tokens=512,
        )
        ok = _run_humaneval(prompt, out["text"] or "", item["test"], item["entry_point"])
        rows.append({"id": item.get("task_id"), "ok": ok, "pred": (out["text"] or "")[:200]})
    return rows
