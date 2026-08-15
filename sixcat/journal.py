"""Append-only JSONL journal so a crash can resume mid-battery."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class TimeBudget:
    def __init__(self, seconds: float | None):
        self.seconds = seconds
        self.start = time.monotonic()

    def expired(self) -> bool:
        if self.seconds is None:
            return False
        return (time.monotonic() - self.start) >= self.seconds

    def remaining(self) -> float | None:
        if self.seconds is None:
            return None
        return max(0.0, self.seconds - (time.monotonic() - self.start))


class RunJournal:
    def __init__(self, path: Path, resume: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._done: dict[tuple[str, str], dict[str, Any]] = {}
        if resume and self.path.exists():
            self._load()
            self._fh = self.path.open("a", encoding="utf-8")
        else:
            self._fh = self.path.open("w", encoding="utf-8")

    def _load(self) -> None:
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cat = rec.get("cat")
                key = rec.get("key")
                if cat is None or key is None:
                    continue
                self._done[(str(cat), str(key))] = rec

    def done_keys(self) -> set[tuple[str, str]]:
        return set(self._done)

    def get(self, cat: str, key: str) -> dict[str, Any] | None:
        return self._done.get((cat, str(key)))

    def rows_for(self, cat: str) -> list[dict[str, Any]]:
        return [v for (c, _), v in self._done.items() if c == cat]

    def append(self, rec: dict[str, Any]) -> None:
        cat = str(rec["cat"])
        key = str(rec["key"])
        rec = dict(rec)
        rec["cat"] = cat
        rec["key"] = key
        rec.setdefault("ts", time.time())
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()
        self._done[(cat, key)] = rec

    def close(self) -> None:
        if getattr(self, "_fh", None):
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "RunJournal":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class Session:
    def __init__(self, journal: RunJournal, budget: TimeBudget):
        self.journal = journal
        self.budget = budget
        self.stopped = False

    def begin(self, cat: str, key: str):
        if self.budget.expired():
            if not self.stopped:
                print(f"TIMEUP before {cat}/{key}", flush=True)
            self.stopped = True
            return "stop"
        cached = self.journal.get(cat, str(key))
        if cached:
            print(f"SKIP {cat}/{key}", flush=True)
            return cached
        return None

    def finish(self, cat: str, key: str, row: dict[str, Any]) -> dict[str, Any]:
        rec = dict(row)
        rec["cat"] = cat
        rec["key"] = str(key)
        rec.setdefault("id", key)
        self.journal.append(rec)
        mark = "PASS" if rec.get("ok") else "FAIL"
        bits = [f"{mark} {cat}/{key}"]
        if rec.get("pred") is not None:
            bits.append(f"pred={rec.get('pred')}")
        if rec.get("gold") is not None:
            bits.append(f"gold={rec.get('gold')}")
        print(" ".join(str(b) for b in bits), flush=True)
        return rec


def gate(session: Session | None, cat: str, key: str):
    if session is None:
        return None
    return session.begin(cat, key)


def emit(session: Session | None, cat: str, key: str, row: dict[str, Any]) -> dict[str, Any]:
    rec = dict(row)
    rec.setdefault("id", key)
    if session is None:
        return rec
    return session.finish(cat, key, rec)
