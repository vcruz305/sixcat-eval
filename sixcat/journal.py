"""Append-only JSONL journal so a crash can resume mid-battery."""

from __future__ import annotations

import copy
import json
import math
import uuid
import warnings
from urllib.parse import urlsplit
from .storage import JournalLock
import threading
import time
from pathlib import Path
from typing import Any, Callable


class TimeBudget:
    def __init__(self, seconds: float | None):
        if seconds is not None and (not math.isfinite(seconds) or seconds < 0):
            raise ValueError("time budget must be finite and non-negative")
        self.seconds = seconds
        self.start = time.monotonic()

    @property
    def deadline(self) -> float | None:
        return None if self.seconds is None else self.start + self.seconds

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
    RETRY_KEY = "_sixcat_retry"

    def __init__(self, path: Path, resume: bool = True, identity: dict[str, Any] | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._done: dict[tuple[str, str], dict[str, Any]] = {}
        self.identity = self._normalise_identity(identity)
        self._loaded_identity: dict[str, Any] | None = None
        self._first: dict[tuple[str, str], dict[str, Any]] = {}
        self._attempts: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.events: list[dict[str, Any]] = []
        self.recovered_tail_bytes = 0
        self._writer_lock = JournalLock(self.path)

        try:
            if resume and self.path.exists():
                self._load()
                if self.identity is not None:
                    if self._loaded_identity is None and self._done:
                        raise ValueError(
                            f"cannot resume {self.path}: existing journal is missing run identity; "
                            "use --no-resume or a fresh log"
                        )
                    if self._loaded_identity is not None and self._loaded_identity != self.identity:
                        changed = self.identity_changes(self._loaded_identity, self.identity)
                        if changed:
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
        except BaseException:
            self._writer_lock.close()
            raise

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

    @staticmethod
    def _is_loopback_base_url(value: Any) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        try:
            return urlsplit(value).hostname in {"127.0.0.1", "localhost", "::1"}
        except ValueError:
            return False

    @classmethod
    def identity_changes(
        cls,
        loaded: dict[str, Any],
        incoming: dict[str, Any],
        *,
        ignore: set[str] | frozenset[str] = frozenset(),
    ) -> list[str]:
        changed = []
        for key in sorted(set(loaded) | set(incoming)):
            if key in ignore:
                continue
            if (
                key == "base_url"
                and cls._is_loopback_base_url(loaded.get(key))
                and cls._is_loopback_base_url(incoming.get(key))
                and loaded.get("verified_upstream")
                and loaded.get("verified_upstream") == incoming.get("verified_upstream")
            ):
                continue
            if key == "transport":
                loaded_t = loaded.get(key) or "openai"
                incoming_t = incoming.get(key) or "openai"
                if loaded_t == incoming_t:
                    continue
            if loaded.get(key) != incoming.get(key):
                changed.append(key)
        return changed

    def _write_identity_header(self) -> None:
        self._fh.write(json.dumps({self.HEADER_KEY: self.identity}, ensure_ascii=False) + "\n")
        self._fh.flush()
        self._loaded_identity = copy.deepcopy(self.identity)

    def _record(self, rec: dict[str, Any]) -> None:
        ident = (str(rec["cat"]), str(rec["key"]))
        saved = copy.deepcopy(rec)
        self._attempts.setdefault(ident, []).append(saved)
        if rec.get("scored", True):
            self._done[ident] = saved
            self._first.setdefault(ident, saved)

    def _load(self) -> None:
        raw = self.path.read_bytes()
        lines = raw.splitlines(keepends=True)
        offset = 0
        for index, raw_line in enumerate(lines):
            try:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    offset += len(raw_line)
                    continue
                rec = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                if index == len(lines) - 1 and not raw_line.endswith(b"\n"):
                    backup = self.path.with_name(self.path.name + ".torn-" + uuid.uuid4().hex + ".bin")
                    backup.write_bytes(raw_line)
                    with self.path.open("r+b") as handle:
                        handle.truncate(offset)
                    self.recovered_tail_bytes = len(raw_line)
                    warnings.warn(f"recovered {len(raw_line)} torn journal bytes; preserved at {backup}", RuntimeWarning)
                    return
                raise ValueError(f"corrupt journal record at line {index + 1} in {self.path}") from exc
            offset += len(raw_line)
            if not isinstance(rec, dict):
                raise ValueError(f"journal record {index + 1} must be an object")
            if self.HEADER_KEY in rec:
                loaded = self._normalise_identity(rec[self.HEADER_KEY])
                if self._loaded_identity is not None and loaded != self._loaded_identity:
                    raise ValueError(f"journal {self.path} contains conflicting run identity headers")
                self._loaded_identity = loaded
            elif "cat" in rec and "key" in rec:
                self._record(rec)
            else:
                self.events.append(rec)
        # Even a complete last JSON value needs a separator before the next append.
        if raw and not raw.endswith(b"\n"):
            with self.path.open("ab") as handle:
                handle.write(b"\n")

    def first_rows_for(self, cat: str) -> list[dict[str, Any]]:
        return copy.deepcopy([row for (category, _), row in self._first.items() if category == cat])

    def first(self, cat: str, key: str) -> dict[str, Any] | None:
        return copy.deepcopy(self._first.get((cat, str(key))))

    def attempts_for(self, cat: str, key: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self._attempts.get((cat, str(key)), []))

    def all_attempts(self) -> list[dict[str, Any]]:
        return copy.deepcopy([row for attempts in self._attempts.values() for row in attempts])

    def done_keys(self) -> set[tuple[str, str]]:
        return set(self._done)

    def failed_keys(self) -> set[tuple[str, str]]:
        return {ident for ident, rec in self._done.items() if rec.get("ok") is not True}

    def get(self, cat: str, key: str) -> dict[str, Any] | None:
        return copy.deepcopy(self._done.get((cat, str(key))))

    def rows_for(self, cat: str) -> list[dict[str, Any]]:
        return copy.deepcopy([v for (c, _), v in self._done.items() if c == cat])

    def append_event(self, rec: dict[str, Any]) -> None:
        payload = dict(rec)
        payload.setdefault("ts", time.time())
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            self._fh.write(line)
            self._fh.flush()
            self.events.append(copy.deepcopy(payload))

    def append(self, rec: dict[str, Any]) -> None:
        cat = str(rec["cat"])
        key = str(rec["key"])
        rec = dict(rec)
        rec["cat"] = cat
        rec["key"] = key
        rec.setdefault("ts", time.time())
        with self._lock:
            rec["attempt"] = len(self._attempts.get((cat, key), [])) + 1
            line = json.dumps(rec, ensure_ascii=False, allow_nan=False) + "\n"
            self._fh.write(line)
            self._fh.flush()
            self._record(rec)

    def close(self) -> None:
        with self._lock:
            if getattr(self, "_fh", None):
                self._fh.close()
                self._fh = None
            self._writer_lock.close()

    def __enter__(self) -> "RunJournal":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class Session:
    def __init__(
        self,
        journal: RunJournal,
        budget: TimeBudget,
        *,
        retry_failed: bool = False,
        include_remaining: bool = True,
        retry_mode: str | None = None,
        concurrency: int = 1,
    ):
        self.journal = journal
        self.budget = budget
        self.stopped = False
        self.retry_failed = retry_failed
        self.include_remaining = include_remaining
        self.retry_mode = retry_mode
        self.concurrency = max(1, int(concurrency))
        self._gate_lock = threading.Lock()
        self.collecting = False
        self.pending_tasks = []
        self.plan_keys: list[tuple[str, str]] = []
        self.segment_id = uuid.uuid4().hex
        self.segment_started = time.monotonic()
        self.segment_attempts: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.retry_keys = journal.failed_keys() if retry_failed else set()
        self.rescored: set[tuple[str, str]] = set()
        if self.retry_keys:
            journal.append_event(
                {
                    journal.RETRY_KEY: {
                        "mode": retry_mode or ("failed" if retry_failed else "remaining"),
                        "keys": [f"{cat}/{key}" for cat, key in sorted(self.retry_keys)],
                    }
                }
            )

    def begin(self, cat: str, key: str):
        ident = (cat, str(key))
        with self._gate_lock:
            if ident not in self.plan_keys:
                self.plan_keys.append(ident)
            cached = self.journal.get(cat, str(key))
            wants_retry = ident in self.retry_keys
            if self.budget.expired() and not self.collecting:
                if not self.stopped:
                    print(f"TIMEUP before {cat}/{key}", flush=True)
                self.stopped = True
                return cached if cached is not None else "stop"
            if wants_retry:
                return None
            if cached:
                print(f"SKIP {cat}/{key}", flush=True)
                return cached
            if not self.include_remaining:
                return "omit"
            return None

    def finish(self, cat: str, key: str, row: dict[str, Any]) -> dict[str, Any]:
        rec = dict(row)
        rec["cat"] = cat
        rec["key"] = str(key)
        rec.setdefault("id", key)
        rec["segment_id"] = self.segment_id
        with self._gate_lock:
            self.journal.append(rec)
            if not rec.get("generation_reused"):
                self.segment_attempts.append(copy.deepcopy(rec))
            ident = (cat, str(key))
            if ident in self.retry_keys:
                self.rescored.add(ident)
            mark = "PASS" if rec.get("ok") else "FAIL"
            bits = [f"{mark} {cat}/{key}"]
            if rec.get("pred") is not None:
                bits.append(f"pred={rec.get('pred')}")
            if rec.get("gold") is not None:
                bits.append(f"gold={rec.get('gold')}")
            print(" ".join(str(b) for b in bits), flush=True)
        return rec

    def continuation_receipt(self) -> dict[str, Any]:
        failed_kept = sorted(
            f"{cat}/{key}" for cat, key in (self.retry_keys - self.rescored)
        )
        return {
            "retry": self.retry_mode,
            "merged": True,
            "failed_requested": len(self.retry_keys),
            "failed_rescored": len(self.rescored),
            "failed_kept_previous": len(failed_kept),
            "failed_kept_keys": failed_kept,
        }


def gate(session: Session | None, cat: str, key: str):
    if session is None:
        return None
    return session.begin(cat, key)


def apply_item_gate(session: Session | None, cat: str, key: str, rows: list[dict[str, Any]]) -> str:
    """Return 'run', 'skip', or 'stop' after applying cache/retry/time-budget rules."""
    outcome = gate(session, cat, key)
    if outcome == "stop":
        return "stop"
    if outcome == "omit":
        return "skip"
    if isinstance(outcome, dict):
        rows.append(outcome)
        return "skip"
    return "run"


def emit(session: Session | None, cat: str, key: str, row: dict[str, Any]) -> dict[str, Any]:
    rec = dict(row)
    rec.setdefault("id", key)
    if session is None:
        return rec
    return session.finish(cat, key, rec)


def concurrency_of(session: Session | None) -> int:
    if session is None:
        return 1
    return max(1, int(getattr(session, "concurrency", 1) or 1))


def run_pending(
    session: Session | None, cat: str, pending: list[tuple[str, Any]],
    worker: Callable[[Any], dict[str, Any]], rows: list[dict[str, Any]],
) -> str:
    """Schedule bounded work, or collect it for the battery's global ranked queue."""
    from .scheduler import Task, execute_tasks
    tasks = [Task(cat, key, payload, worker, rows) for key, payload in pending]
    if session is not None and session.collecting:
        session.pending_tasks.extend(tasks)
        return "run"
    return execute_tasks(tasks, session)
