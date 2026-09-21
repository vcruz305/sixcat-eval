"""Retain a returned completion if its local grader is interrupted.

Resuming an infrastructure/grading interruption must not silently give the
model a new attempt. Every category uses this single completion boundary.
"""
from __future__ import annotations
import copy
import threading
from contextlib import contextmanager

_local = threading.local()

class ItemProcessingError(Exception):
    def __init__(self, cause: Exception, response: dict | None):
        super().__init__(type(cause).__name__)
        self.cause, self.response = cause, response

@contextmanager
def response_context(replay=None):
    previous = getattr(_local, "state", None)
    state = {"replay": replay, "captured": None}
    _local.state = state
    try:
        yield
    except (AssertionError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        raise ItemProcessingError(exc, state["captured"]) from exc
    finally:
        _local.state = previous

def complete_for_item(client, prompt: str, **kwargs):
    state = getattr(_local, "state", None)
    replay = state["replay"] if state is not None else None
    if replay is not None:
        if replay.get("_sixcat_prompt") != prompt:
            raise ValueError("deferred response prompt mismatch")
        out = copy.deepcopy(replay)
        out["generation_reused"] = True
        state["replay"] = None
    else:
        out = client.complete(prompt, **kwargs)
        out = copy.deepcopy(out)
        out["_sixcat_prompt"] = prompt
    if state is not None:
        state["captured"] = copy.deepcopy(out)
    return out
