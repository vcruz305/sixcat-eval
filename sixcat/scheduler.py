"""Bounded, deadline-aware dispatch. No unbounded executor backlog."""
from __future__ import annotations

import copy
import time
from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable

from .runtime import DeadlineExceeded, deadline_scope
from .generation import ItemProcessingError, response_context
from .receipts import completion_row
from .score import CATEGORIES

@dataclass
class Task:
    cat: str
    key: str
    payload: Any
    worker: Callable[[Any], dict]
    rows: list[dict]


def balanced_order(tasks: list[Task]) -> list[Task]:
    """Round-robin category ranks; preserve each frozen hardest-first order."""
    queues = defaultdict(deque)
    for task in tasks:
        queues[task.cat].append(task)
    result = []
    categories = list(CATEGORIES) + sorted(set(queues) - set(CATEGORIES))
    while any(queues.values()):
        for cat in categories:
            if queues[cat]:
                result.append(queues[cat].popleft())
    return result


def execute_tasks(tasks: list[Task], session=None) -> str:
    if not tasks:
        return "run"
    concurrency = session.concurrency if session is not None else 1
    budget = session.budget if session is not None else None

    def expired():
        return bool(budget is not None and budget.expired())

    def invoke(task):
        if expired():
            raise DeadlineExceeded("benchmark deadline reached before item start")
        replay = None
        if session is not None:
            attempts = session.journal.attempts_for(task.cat, task.key)
            if attempts and attempts[-1].get("scored") is False:
                replay = attempts[-1].get("deferred_response")
        with deadline_scope(budget.deadline if budget is not None else None), response_context(replay):
            return task.worker(task.payload)

    def collect(task, row=None, error=None):
        if error is not None:
            if session is None:
                raise error
            # Infra errors never become a model FAIL and never consume first-response
            # scoring. Do not persist exception strings which can contain secrets.
            response = error.response if isinstance(error, ItemProcessingError) else None
            error = error.cause if isinstance(error, ItemProcessingError) else error
            rec = {"cat": task.cat, "key": task.key, "ok": None, "scored": False,
                   "status": "deadline" if expired() or isinstance(error, DeadlineExceeded) else "error",
                   "error_type": type(error).__name__, "segment_id": session.segment_id}
            if response is not None:
                rec = {**completion_row(response), **rec, "deferred_response": response}
                if not response.get("generation_reused"):
                    session.segment_attempts.append(copy.deepcopy(rec))
            session.journal.append(rec)
            session.errors.append({key: value for key, value in rec.items() if key != "deferred_response"})
            if rec["status"] == "deadline":
                session.stopped = True
            print(f"{rec['status'].upper()} {task.cat}/{task.key} ({rec['error_type']})", flush=True)
            return
        if session is not None:
            row = session.finish(task.cat, task.key, row)
        else:
            row = dict(row)
            row.setdefault("id", task.key)
        task.rows.append(row)

    cursor = 0
    # At most N futures exist. Workers recheck the deadline before model traffic.
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="sixcat-item") as pool:
        active = {}
        while cursor < len(tasks) or active:
            while cursor < len(tasks) and len(active) < concurrency and not expired():
                task = tasks[cursor]
                cursor += 1
                active[pool.submit(invoke, task)] = task
            if not active:
                break
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                task = active.pop(future)
                try:
                    row = future.result()
                except (AssertionError, KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    collect(task, error=exc)
                else:
                    collect(task, row=row)
    if session is not None and (cursor < len(tasks) or expired()):
        session.stopped = True
    return "stop" if session is not None and session.stopped else "run"


def segment_receipt(session, rows, elapsed=None):
    elapsed = time.monotonic() - session.segment_started if elapsed is None else elapsed
    measured = [r for r in rows if isinstance(r.get("ctok"), int) and not isinstance(r.get("ctok"), bool) and r["ctok"] >= 0]
    total = sum(r["ctok"] for r in measured)
    return {"id": session.segment_id, "concurrency": session.concurrency,
            "elapsed_s": elapsed, "responses": len(rows), "token_counted_responses": len(measured),
            "completion_tokens": total,
            "throughput_tps": total / elapsed if elapsed > 0 and measured else None,
            "throughput_coverage": f"{len(measured)}/{len(rows)}",
            "errors": len(session.errors), "deadline_reached": session.stopped}
