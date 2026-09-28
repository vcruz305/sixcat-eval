"""Pooled HTTP transport with a TOTAL deadline, not just a socket-idle timeout.

HTTPX async streaming and asyncio.timeout are used so even a slow-drip response
is cancelled. The loop belongs to this transport, not the caller's event loop.
No completion is automatically retried. Sources: python-httpx.org/async/ and
Python's asyncio timeout/run_coroutine_threadsafe documentation.
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import io
import json
import threading
import time
import urllib.error

import httpx

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class ResponseBody(io.BytesIO):
    def __init__(self, body: bytes, first_token_at: float | None = None):
        super().__init__(body)
        self.first_token_at = first_token_at


def sse_line_has_completion_token(line: bytes) -> bool:
    """True when an SSE line carries a generated token, not an empty role delta."""
    try:
        text = line.decode("utf-8").strip()
    except UnicodeDecodeError:
        return False
    if not text.startswith("data:"):
        return False
    raw = text[5:].strip()
    if not raw or raw == "[DONE]":
        return False
    try:
        chunk = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(chunk, dict):
        return False
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return False
    choice = choices[0]
    sources = []
    if isinstance(choice.get("delta"), dict):
        sources.append(choice["delta"])
    if isinstance(choice.get("message"), dict):
        sources.append(choice["message"])
    for source in sources:
        for key in ("content", "reasoning_content", "reasoning"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return True
        tools = source.get("tool_calls")
        if isinstance(tools, list) and any(isinstance(item, dict) for item in tools):
            return True
    return False

class HTTPTransport:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = False
        self._client = None
        self._thread = threading.Thread(target=self._serve, name="sixcat-http", daemon=True)
        self._thread.start()
        self._ready.wait()

    def _serve(self):
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        self._loop.close()

    async def _request(self, request, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request deadline reached")
        async with asyncio.timeout(remaining):
            if self._client is None:
                self._client = httpx.AsyncClient(
                    limits=httpx.Limits(max_connections=128, max_keepalive_connections=32),
                    follow_redirects=False,
                )
            async with self._client.stream(
                request.get_method(), request.full_url,
                headers=dict(request.header_items()), content=request.data,
                timeout=remaining,
            ) as response:
                body = bytearray()
                pending = bytearray()
                first_token_at = None
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ValueError("HTTP response exceeds 16 MiB safety limit")
                    body.extend(chunk)
                    if first_token_at is None:
                        pending.extend(chunk)
                        while b"\n" in pending:
                            line, _, pending = pending.partition(b"\n")
                            if sse_line_has_completion_token(line):
                                first_token_at = time.perf_counter()
                                break
                if first_token_at is None and pending and sse_line_has_completion_token(pending):
                    first_token_at = time.perf_counter()
                if response.status_code >= 300:
                    raise urllib.error.HTTPError(
                        request.full_url, response.status_code, response.reason_phrase,
                        dict(response.headers), io.BytesIO(bytes(body)),
                    )
                return bytes(body), first_token_at

    def open(self, request, timeout):
        if self._closed:
            raise RuntimeError("HTTP transport is closed")
        deadline = time.monotonic() + timeout
        future = asyncio.run_coroutine_threadsafe(self._request(request, deadline), self._loop)
        try:
            # The outer bound also covers loop scheduling. Cancellation closes the
            # response stream; it cannot promise the remote server stops computing.
            body, first_token_at = future.result(timeout=timeout)
            return ResponseBody(body, first_token_at)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError("HTTP total request deadline reached") from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError("HTTP request timed out") from exc
        except httpx.HTTPError as exc:
            # Do not persist provider URLs, credentials, or response bodies in errors.
            raise OSError(f"HTTP transport failure: {type(exc).__name__}") from exc

    def close(self):
        if self._closed:
            return
        self._closed = True
        async def shutdown():
            current = asyncio.current_task()
            tasks = [t for t in asyncio.all_tasks() if t is not current]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._client is not None:
                await self._client.aclose()
        try:
            asyncio.run_coroutine_threadsafe(shutdown(), self._loop).result(timeout=3)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=3)

_transport = None
_lock = threading.Lock()

def open_request(request, timeout):
    global _transport
    with _lock:
        if _transport is None:
            _transport = HTTPTransport()
    return _transport.open(request, timeout)

def close_transport():
    global _transport
    with _lock:
        transport, _transport = _transport, None
    if transport is not None:
        transport.close()

atexit.register(close_transport)
