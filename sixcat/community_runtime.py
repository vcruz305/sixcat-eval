"""In-process public route hints, never authentication or profile data."""
from contextvars import ContextVar
from contextlib import contextmanager

current = ContextVar("sixcat_public_route", default=None)

@contextmanager
def runtime_metadata(target):
    local = target.provider in {"custom", "ollama", "vllm", "llamacpp"}
    token = current.set({"source_kind": "local" if local else "cloud", "source": target.provider,
        "api_wrapper": "Hermes raw-model bridge", "evaluation_client": "Sixcat Hermes bridge"})
    try:
        yield
    finally:
        current.reset(token)
