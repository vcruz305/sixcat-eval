from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data"


def read_jsonl(name: str) -> list[dict[str, Any]]:
    path = DATA / name
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def take(rows: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None or limit < 0:
        return rows
    return rows[:limit]
