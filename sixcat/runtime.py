"""Per-worker monotonic deadline propagated into transport and code execution."""
from __future__ import annotations

import contextlib
import math
import threading
import time

_state = threading.local()

class DeadlineExceeded(TimeoutError):
    """The invocation budget expired; this is not a scored model response."""

@contextlib.contextmanager
def deadline_scope(deadline: float | None):
    previous = getattr(_state, "deadline", None)
    _state.deadline = deadline
    try:
        yield
    finally:
        _state.deadline = previous

def effective_timeout(timeout: float) -> float:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    deadline = getattr(_state, "deadline", None)
    remaining = timeout if deadline is None else min(timeout, deadline - time.monotonic())
    if remaining <= 0:
        raise DeadlineExceeded("benchmark deadline reached")
    return remaining
