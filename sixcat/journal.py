"""Append-only JSONL journal so a crash can resume mid-battery."""

from __future__ import annotations

import copy
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
    HEADER_KEY = "_sixcat_run"

    def __init__(self, path: Path, resume: bool = True, identity: dict[str, Any] | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._done: dict[tuple[str, str], dict[str, Any]] = {}
        self.identity = self._normalise_identity(identity)
        self._loaded_identity: dict[str, Any] | None = None

        if resume and self.path.exists():
            self._load()
            if self.identity is not None:
                if self._loaded_identity is None and self._done:
                    raise ValueError(
                        f"cannot resume {self.path}: existing journal is missing run identity; "
                        "use --no-resume or a fresh log"
                    )
                if self._loaded_identity is not None and self._loaded_identity != self.identity:
                    changed = sorted(
                        key
                        for key in set(self._loaded_identity) | set(self.identity)
                        if self._loaded_identity.get(key) != self.identity.get(key)
                    )
                    raise ValueError(
                        f"cannot resume {self.path}: run identity mismatch in {', '.join(changed)}; "
                        "use --no-resume or a matching log"
                    )
            elif self._loaded_identity is not None:
                self.identity = copy.deepcopy(self._loaded_identity)
            self._fh = self.path.open("a", encoding="utf-8")
            if self.identity is not None and self._loaded_identity is None:
                self._write_identity_header()
        else:
            self._fh = self.path.open("w", encoding="utf-8")
            if self.identity is not None:
                self._write_identity_header()

    @staticmethod
    def _normalise_identity(identity: dict[str, Any] | None) -> dict[str, Any] | None:
        if identity is None:
            return None
        if not isinstance(identity, dict) or not identity:
            raise ValueError("run identity must be a non-empty JSON object")
        try:
            return json.loads(json.dumps(identity, sort_keys=True, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"run identity must be JSON serializable: {exc}") from exc

    def _write_identity_header(self) -> None:
        self._fh.write(json.dumps({self.HEADER_KEY: self.identity}, ensure_ascii=False) + "\n")
        self._fh.flush()
        self._loaded_identity = copy.deepcopy(self.identity)

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
                if not isinstance(rec, dict):
                    continue
                if self.HEADER_KEY in rec:
                    loaded = self._normalise_identity(rec.get(self.HEADER_KEY))
                    if self._loaded_identity is not None and loaded != self._loaded_identity:
                        raise ValueError(f"journal {self.path} contains conflicting run identity headers")
                    self._loaded_identity = loaded
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
