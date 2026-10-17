"""Quick speed regressions using a local HTTP/SSE endpoint; no model required."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from sixcat import perf


class _MockState:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
        self.delay_s = 0.002
        self.include_usage = True


@pytest.fixture
def speed_endpoint():
    state = _MockState()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            body = json.dumps({"object": "list", "data": [{"id": "fixture-reasoner"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with state.lock:
                state.calls.append(payload)

            def chunk(delta, finish_reason=None):
                return {
                    "id": "fixture-completion",
                    "object": "chat.completion.chunk",
                    "model": "fixture-reasoner",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
                }

            events = [
                chunk({"role": "assistant", "content": ""}),
                chunk({"reasoning_content": "Compare the options. "}),
                chunk({"reasoning_content": "The checks agree."}),
                chunk({"content": "The answer "}),
                chunk({"content": "is ready."}),
                chunk({}, "stop"),
            ]
            if state.include_usage:
                events.append({
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 768, "completion_tokens": 12, "total_tokens": 780,
                        "completion_tokens_details": {"reasoning_tokens": 8},
                        "prompt_tokens_details": {"cached_tokens": 0},
                    },
                })
            frames = [("data: " + json.dumps(event) + "\n\n").encode() for event in events]
            frames.append(b"data: [DONE]\n\n")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(sum(map(len, frames))))
            self.end_headers()
            try:
                for frame in frames:
                    if state.delay_s:
                        time.sleep(state.delay_s)
                    self.wfile.write(frame)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _run_speed(tmp_path, speed_endpoint, *extra):
    url, _state = speed_endpoint
    output = tmp_path / "speed.json"
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = perf.main([
                "--base-url", url, "--model", "fixture-reasoner",
                "--api-key", "none", "--out", str(output), *extra,
            ])
        except SystemExit as exc:
            code = exc.code
    result = SimpleNamespace(returncode=code, stdout=stdout.getvalue(), stderr=stderr.getvalue())
    report = json.loads(output.read_text()) if output.exists() else None
    return result, report


def _assert_success(result):
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_default_quick_is_six_calls_with_matching_warmup(tmp_path, speed_endpoint):
    result, report = _run_speed(tmp_path, speed_endpoint)
    _assert_success(result)
    _url, state = speed_endpoint

    assert report["schema"] == "sixcat-speed-v3"
    assert report["requested_profile"] == "quick"
    assert report["requested_profiles"] == ["quick"]
    assert report["thinking_requested"] == "on"
    assert report["samples_per_confirmation"] == 5
    assert report["max_seconds"] == 120
    assert report["status"] == "completed"
    profile = report["profiles"]["quick"]
    assert profile["curve"] is None
    assert profile["selected_concurrency"] == 1
    assert profile["workload"]["prompt_words"] == 512
    assert profile["workload"]["max_tokens"] == 256

    assert len(state.calls) == 6
    assert all(call["max_tokens"] == 256 for call in state.calls)
    assert all(call["chat_template_kwargs"]["enable_thinking"] is True for call in state.calls)
    prompts = [call["messages"][0]["content"] for call in state.calls]
    lengths = [len(prompt.split()) for prompt in prompts]
    # Warmup matches the first measured task; task instructions vary thereafter.
    assert lengths[0] == lengths[1]
    assert min(lengths) >= 512
    assert max(lengths) - min(lengths) <= 16
    assert len(set(prompts)) == 6

    confirmation = profile["confirmation"]
    assert confirmation["requested"] == confirmation["succeeded"] == 5
    assert confirmation["failed"] == 0
    assert confirmation["warmup"]["requested"] == 1
    assert confirmation["warmup_workload"] == {"prompt_words": 512, "max_tokens": 256}
    assert confirmation["http_client_reused_after_warmup"] is True
    assert confirmation["prompt_token_lengths"]["n"] == 5
    assert confirmation["prompt_token_lengths"]["p50"] == 768
    assert confirmation["completion_token_lengths"]["p50"] == 12
    summary = report["summary"]
    assert summary["schema"] == "sixcat-speed-summary-v2"
    assert summary["decode"]["n"] == 5
    assert summary["decode"]["source_concurrency"] == 1
    assert summary["prefill"]["metric"] == "client-effective-prefill"
    assert summary["ttft"]["n"] == summary["ttfo"]["n"] == 5
    assert "effective" in result.stdout.lower()
    assert "n=5" in result.stdout.replace(" ", "")
    assert "best sustained" not in result.stdout.lower()


def test_explicit_thinking_off_is_honored(tmp_path, speed_endpoint):
    result, report = _run_speed(tmp_path, speed_endpoint, "--thinking", "off", "--samples", "2")
    _assert_success(result)
    assert report["thinking_requested"] == "off"
    assert len(speed_endpoint[1].calls) == 3
    assert all(call["chat_template_kwargs"]["enable_thinking"] is False for call in speed_endpoint[1].calls)


@pytest.mark.parametrize("thinking, expected", [("on", True), ("off", False)])
def test_speed_overrides_vendor_policy_thinking(monkeypatch, thinking, expected):
    original = perf.resolve_policy("strict", "fixture-reasoner", seed=7)
    assert original.thinking is False
    monkeypatch.setattr(perf, "resolve_policy", lambda *_args, **_kwargs: original)
    args = argparse.Namespace(
        policy="vendor", model="fixture-reasoner", seed=7,
        policy_family=None, thinking=thinking,
    )
    assert perf._resolve_cli_policy(args).thinking is expected
    assert original.thinking is False


def test_all_profiles_remain_an_explicit_three_profile_suite(tmp_path, speed_endpoint):
    result, report = _run_speed(
        tmp_path, speed_endpoint, "--profile", "all", "--concurrency", "1", "--samples", "2",
    )
    _assert_success(result)
    assert report["requested_profiles"] == ["decode", "balanced", "prefill"]
    assert set(report["profiles"]) == {"decode", "balanced", "prefill"}
    assert report["max_seconds"] == 600
    assert len(speed_endpoint[1].calls) == 9
    for profile in report["profiles"].values():
        assert profile["curve"] is None
        assert profile["confirmation"]["requested"] == profile["confirmation"]["succeeded"] == 2


def test_fixed_and_auto_concurrency_are_mutually_exclusive(tmp_path, speed_endpoint):
    result, _report = _run_speed(
        tmp_path, speed_endpoint, "--concurrency", "1", "--auto-concurrency",
    )
    assert result.returncode != 0
    assert "concurrency" in result.stderr.lower()
    assert speed_endpoint[1].calls == []


def test_usage_absence_does_not_invent_token_rates(tmp_path, speed_endpoint):
    speed_endpoint[1].include_usage = False
    result, report = _run_speed(tmp_path, speed_endpoint, "--samples", "2")
    _assert_success(result)
    confirmation = report["profiles"]["quick"]["confirmation"]
    assert confirmation["succeeded"] == 2
    assert confirmation["aggregate_output_tps"] is None
    assert confirmation["token_count_coverage"] == 0
    assert confirmation["effective_decode_tps"]["n"] == 0
    assert confirmation["effective_prefill_tps"]["n"] == 0


def test_shared_deadline_saves_an_incomplete_report(tmp_path, speed_endpoint):
    speed_endpoint[1].delay_s = 0.1
    result, report = _run_speed(
        tmp_path, speed_endpoint, "--profile", "all", "--concurrency", "1",
        "--samples", "5", "--max-seconds", "1",
    )
    assert result.returncode == 2
    assert report is not None
    assert report["schema"] == "sixcat-speed-v3"
    assert report["status"] == "incomplete"
    assert report["deadline_reached"] is True
    assert report["incomplete_profiles"]
    assert report["profiles"]


def _level(rate, n, concurrency=1):
    return perf._summarize(
        [{
            "ok": True, "prompt_tokens": 768, "completion_tokens": 256,
            "client_ttft_s": 0.1, "client_ttfo_s": 0.5, "e2e_s": 10.0,
            "effective_decode_tps": rate, "effective_prefill_tps": 7680.0,
            "thinking_requested": True,
        } for _ in range(n)],
        elapsed_s=n * 10.0, concurrency=concurrency,
    )


@pytest.mark.parametrize("selected_concurrency", [1, 4])
def test_confirmed_c1_headline_wins_over_discovery(selected_concurrency):
    discovery, confirmed = _level(10.0, 4), _level(30.0, 5)
    profile = {
        "status": "completed",
        "workload": {"profile": "decode", "prompt_words": 32, "max_tokens": 256},
        "selected_concurrency": selected_concurrency,
        "curve": {"levels": [discovery]},
        "confirmation": confirmed if selected_concurrency == 1 else _level(70.0, 5, concurrency=4),
    }
    if selected_concurrency != 1:
        profile["single_stream_confirmation"] = confirmed
    headline = perf.build_speed_summary({"decode": profile})["decode"]
    assert headline["source_concurrency"] == 1
    assert headline["source_phase"] == "confirmation"
    assert headline["n"] == 5
    assert headline["p50_tps"] == 30.0


def test_partial_token_coverage_suppresses_aggregate_throughput():
    summary = perf._summarize(
        [{"ok": True, "prompt_tokens": 100, "completion_tokens": 20},
         {"ok": True, "completion_tokens": None}],
        elapsed_s=2.0, concurrency=1,
    )
    assert summary["aggregate_output_tps"] is None
    assert summary["completion_tokens"] is None
    assert summary["known_completion_tokens"] == 20
    assert summary["token_count_coverage"] == 0.5
    assert summary["token_counted_requests"] == 1


def test_failed_discovery_preserves_diagnostics(monkeypatch):
    def failed_level(_client, **kwargs):
        return perf._summarize(
            [{"ok": False, "error_type": "HTTP503"} for _ in range(kwargs["requests"])],
            elapsed_s=0.01, concurrency=kwargs["concurrency"],
        )
    monkeypatch.setattr(perf, "run_level", failed_level)
    with pytest.raises(perf.ConcurrencyDiscoveryError) as caught:
        perf.discover_concurrency(object(), candidates=[1, 2], max_seconds=1)
    assert caught.value.curve["warmup"]["failed"] == 1
    assert caught.value.curve["measured_levels"] == [1, 2]
    assert all(level["failed"] > 0 for level in caught.value.curve["levels"])
