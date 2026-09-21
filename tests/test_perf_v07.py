from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from sixcat.client import ChatClient
from sixcat.perf import (
    _sample_from_stream,
    confirmation_run,
    discover_concurrency,
    main as speed_main,
    parse_candidates,
    recommend_concurrency,
    resolve_workloads,
    server_metric_status,
)
from sixcat.policy import strict_policy


@contextmanager
def streaming_endpoint(*, reject_stream_options: bool = False):
    state = {"active": 0, "max_active": 0, "posts": 0, "fallbacks": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _json(self, value):
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/props":
                self._json({"n_ctx": 32768, "model_alias": "fixture"})
            else:
                self._json({"object": "list", "data": [{"id": "fixture", "max_model_len": 32768}]})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                state["posts"] += 1
            if not payload.get("stream"):
                self._json({
                    "model": "fixture",
                    "choices": [{"message": {"content": "A", "tool_calls": []}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 32, "completion_tokens": 1},
                })
                return
            if reject_stream_options and "stream_options" in payload:
                with lock:
                    state["fallbacks"] += 1
                body = b'{"error":{"message":"stream_options unsupported"}}'
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            with lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()

                def send(value):
                    self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
                    self.wfile.flush()

                send({"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]})
                time.sleep(0.012)
                send({"choices": [{"delta": {"content": "alpha"}, "finish_reason": None}]})
                time.sleep(0.012)
                send({"choices": [{"delta": {"content": " beta"}, "finish_reason": None}]})
                send({
                    "choices": [],
                    "usage": {"prompt_tokens": 240, "completion_tokens": 12},
                    "timings": {
                        "prompt_n": 240,
                        "prompt_per_second": 1200.0,
                        "predicted_n": 12,
                        "predicted_per_second": 80.0,
                    },
                    "metrics": {
                        "time_to_first_token_ms": 9.0,
                        "queue_time_ms": 1.5,
                        "generation_time_ms": 14.0,
                        "mean_itl_ms": 1.2,
                        "tokens_per_second": 75.0,
                    },
                })
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True
            finally:
                with lock:
                    state["active"] -= 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_candidate_parser_and_knee_prefers_smallest_near_peak():
    assert parse_candidates("2,8,4,4") == [1, 2, 4, 8]
    levels = [
        {"concurrency": 1, "succeeded": 4, "success_rate": 1.0, "aggregate_output_tps": 40.0, "request_rps": 1.0},
        {"concurrency": 2, "succeeded": 4, "success_rate": 1.0, "aggregate_output_tps": 70.0, "request_rps": 2.0},
        {"concurrency": 4, "succeeded": 8, "success_rate": 1.0, "aggregate_output_tps": 100.0, "request_rps": 3.0},
        {"concurrency": 8, "succeeded": 16, "success_rate": 1.0, "aggregate_output_tps": 108.0, "request_rps": 3.1},
    ]
    result = recommend_concurrency(levels)
    assert result["peak_concurrency"] == 8
    assert result["recommended_concurrency"] == 4
    assert result["recommended_fraction_of_peak"] > .92


def test_knee_falls_back_to_request_rate_without_token_usage():
    levels = [
        {"concurrency": 1, "succeeded": 4, "success_rate": 1.0, "aggregate_output_tps": None, "request_rps": 1.0},
        {"concurrency": 2, "succeeded": 4, "success_rate": 1.0, "aggregate_output_tps": None, "request_rps": 1.9},
        {"concurrency": 4, "succeeded": 8, "success_rate": 1.0, "aggregate_output_tps": None, "request_rps": 2.0},
    ]
    result = recommend_concurrency(levels)
    assert result["selection_metric"] == "request_rps"
    assert result["recommended_concurrency"] == 2


def test_stream_sample_separates_client_and_provider_metrics():
    sample = _sample_from_stream(
        started=10.0,
        first_output=10.1,
        ended=11.1,
        usage={"prompt_tokens": 100, "completion_tokens": 11},
        timings={"prompt_per_second": 500.0, "predicted_per_second": 50.0},
        metrics={"time_to_first_token_ms": 80.0, "queue_time_ms": 5.0, "mean_itl_ms": 12.0},
        meta_info={},
        chunks=3,
        compatibility_mode="stream+usage",
    )
    assert sample["client_ttft_s"] == pytest.approx(.1)
    assert sample["provider_ttft_s"] == pytest.approx(.08)
    assert sample["provider_queue_s"] == pytest.approx(.005)
    assert sample["effective_prefill_tps"] == pytest.approx(1000)
    assert sample["effective_decode_tps"] == pytest.approx(10)
    assert sample["server_prefill_tps"] == 500
    assert sample["server_decode_tps"] == 50
    assert sample["provider_effective_prefill_tps"] == pytest.approx(1250)
    assert sample["provider_effective_decode_tps"] is None


def test_confirmation_streams_concurrently_and_reports_tail_metrics():
    with streaming_endpoint() as (url, state):
        client = ChatClient(url, "fixture", strict_policy(), timeout=5)
        result = confirmation_run(
            client,
            concurrency=4,
            samples=12,
            prompt_words=64,
            max_tokens=32,
            deadline=time.monotonic() + 5,
        )
    assert result["succeeded"] == 12
    assert state["max_active"] >= 2
    assert result["aggregate_output_tps"] > 0
    assert result["ttft"]["p95"] >= result["ttft"]["p50"] > 0
    assert result["ttft"]["p99"] >= result["ttft"]["p95"]
    assert result["e2e"]["p99"] >= result["e2e"]["p95"]
    assert result["server_prefill_tps"]["p50"] == 1200
    assert result["server_decode_tps"]["p50"] == 80
    assert result["provider_ttft"]["p50"] == pytest.approx(.009)
    assert result["provider_effective_prefill_tps"]["p50"] > 0
    assert result["provider_effective_decode_tps"]["p50"] > 0
    assert result["p99_sample_warning"] is True


def test_stream_options_has_one_compatibility_fallback():
    with streaming_endpoint(reject_stream_options=True) as (url, state):
        client = ChatClient(url, "fixture", strict_policy(), timeout=5)
        result = confirmation_run(
            client,
            concurrency=2,
            samples=4,
            prompt_words=64,
            max_tokens=32,
            deadline=time.monotonic() + 5,
        )
    assert result["succeeded"] == 4
    assert state["fallbacks"] == 5
    assert state["posts"] == 10
    assert result["aggregate_output_tps"] > 0
    assert result["request_rps"] > 0


def test_discovery_uses_curve_and_returns_auditable_recommendation():
    fake_levels = {
        1: {"concurrency": 1, "requested": 4, "succeeded": 4, "failed": 0, "success_rate": 1.0,
            "elapsed_s": 1.0, "request_rps": 4.0, "aggregate_output_tps": 50.0},
        2: {"concurrency": 2, "requested": 4, "succeeded": 4, "failed": 0, "success_rate": 1.0,
            "elapsed_s": 1.0, "request_rps": 4.0, "aggregate_output_tps": 85.0},
        4: {"concurrency": 4, "requested": 8, "succeeded": 8, "failed": 0, "success_rate": 1.0,
            "elapsed_s": 1.0, "request_rps": 8.0, "aggregate_output_tps": 100.0},
        8: {"concurrency": 8, "requested": 16, "succeeded": 16, "failed": 0, "success_rate": 1.0,
            "elapsed_s": 1.0, "request_rps": 16.0, "aggregate_output_tps": 104.0},
    }
    client = ChatClient("http://127.0.0.1:1/v1", "fixture", strict_policy(), timeout=5)
    with patch("sixcat.perf.run_level", side_effect=lambda client, **kwargs: fake_levels[kwargs["concurrency"]]):
        curve = discover_concurrency(client, candidates=[1, 2, 4, 8], max_seconds=10)
    assert curve["unscored"] is True
    assert curve["synthetic_prompts"] is True
    assert curve["peak_concurrency"] == 8
    assert curve["recommended_concurrency"] == 4
    assert curve["selection_metric"] == "aggregate_output_tps"


def test_speed_cli_fixed_concurrency_writes_json(tmp_path):
    output = tmp_path / "speed.json"
    with streaming_endpoint() as (url, state):
        rc = speed_main([
            "--base-url", url,
            "--model", "fixture",
            "--concurrency", "2",
            "--profile", "custom",
            "--samples", "6",
            "--prompt-words", "64",
            "--max-tokens", "32",
            "--max-seconds", "10",
            "--out", str(output),
        ])
    assert rc == 0
    report = json.loads(output.read_text())
    assert report["schema"] == "sixcat-speed-v2"
    assert report["selected_concurrency"] == 2
    assert report["curve"] is None
    assert report["confirmation"]["ttft"]["p95"] > 0
    assert report["confirmation"]["server_decode_tps"]["p50"] == 80
    assert state["max_active"] >= 2



def test_scored_run_auto_concurrency_records_curve_and_selected_level(tmp_path):
    from sixcat.__main__ import main
    output = tmp_path / "auto.json"
    with streaming_endpoint() as (url, _):
        rc = main([
            "--base-url", url,
            "--model", "fixture",
            "--limit", "1",
            "--skip-code-exec",
            "--auto-concurrency",
            "--concurrency-candidates", "1,2",
            "--calibration-seconds", "5",
            "--calibration-prompt-words", "32",
            "--calibration-max-tokens", "8",
            "--max-minutes", "1",
            "--out", str(output),
            "--no-resume",
        ])
    assert rc == 0
    result = json.loads(output.read_text())
    assert result["performance_calibration"]["unscored"] is True
    assert result["concurrency"] == result["performance_calibration"]["recommended_concurrency"]
    assert result["performance_calibration"]["measured_levels"] == [1, 2]
    assert result["n"] == {"knowledge": 1, "math": 1, "truth": 1, "instruct": 1, "code": 0, "tools": 1}



def test_default_workload_profiles_are_distinct_and_purpose_built():
    workloads = {item["name"]: item for item in resolve_workloads("all")}
    assert set(workloads) == {"decode", "balanced", "prefill"}
    assert workloads["decode"]["prompt_words"] == 32
    assert workloads["decode"]["max_tokens"] == 512
    assert workloads["balanced"]["prompt_words"] == 256
    assert workloads["balanced"]["max_tokens"] == 128
    assert workloads["prefill"]["prompt_words"] == 2048
    assert workloads["prefill"]["max_tokens"] == 32


def test_knee_rejects_failed_levels_and_reports_max_usable_concurrency():
    levels = [
        {"concurrency": 1, "succeeded": 4, "requested": 4, "success_rate": 1.0,
         "aggregate_output_tps": 40.0, "request_rps": 1.0},
        {"concurrency": 2, "succeeded": 4, "requested": 4, "success_rate": 1.0,
         "aggregate_output_tps": 75.0, "request_rps": 2.0},
        {"concurrency": 4, "succeeded": 8, "requested": 8, "success_rate": 1.0,
         "aggregate_output_tps": 100.0, "request_rps": 3.0},
        {"concurrency": 8, "succeeded": 2, "requested": 16, "success_rate": 0.125,
         "aggregate_output_tps": 110.0, "request_rps": 0.2},
    ]
    result = recommend_concurrency(levels, min_success_rate=.95)
    assert result["peak_concurrency"] == 4
    assert result["recommended_concurrency"] == 4
    assert result["max_usable_concurrency"] == 4
    assert result["rejected_concurrency"] == [8]
    assert levels[-1]["usable"] is False


def test_curve_and_confirmation_use_same_requested_workload():
    calls = []
    def fake_level(client, **kwargs):
        calls.append(kwargs)
        c = kwargs["concurrency"]
        return {
            "concurrency": c, "requested": 4, "succeeded": 4, "failed": 0,
            "success_rate": 1.0, "elapsed_s": 1.0, "request_rps": 4.0,
            "aggregate_output_tps": 100.0,
        }
    client = ChatClient("http://127.0.0.1:1/v1", "fixture", strict_policy(), timeout=5)
    with patch("sixcat.perf.run_level", side_effect=fake_level):
        curve = discover_concurrency(
            client,
            candidates=[1, 2],
            max_seconds=10,
            prompt_words=32,
            max_tokens=512,
        )
    measured = [call for call in calls if str(call.get("phase", "")).startswith("curve-")]
    assert measured
    assert all(call["prompt_words"] == 32 for call in measured)
    assert all(call["max_tokens"] == 512 for call in measured)
    assert curve["prompt_words"] == 32
    assert curve["max_tokens"] == 512


def test_server_metric_status_explains_unavailable_route():
    result = {
        name: {"n": 0}
        for name in (
            "server_prefill_tps", "server_decode_tps", "provider_ttft",
            "provider_queue", "provider_mean_itl",
            "provider_effective_prefill_tps", "provider_effective_decode_tps",
        )
    }
    status = server_metric_status(
        result,
        {"source": "openai_models", "llama_cpp_props": None, "props_error": "404"},
    )
    assert status["available"] is False
    assert "no llama.cpp /props" in status["reason"]


def test_one_command_runs_decode_balanced_and_prefill_suite(tmp_path):
    output = tmp_path / "suite.json"
    with streaming_endpoint() as (url, _):
        rc = speed_main([
            "--base-url", url,
            "--model", "fixture",
            "--concurrency", "2",
            "--samples", "2",
            "--max-seconds", "20",
            "--out", str(output),
        ])
    assert rc == 0
    report = json.loads(output.read_text())
    assert report["schema"] == "sixcat-speed-v2"
    assert report["requested_profile"] == "all"
    assert set(report["profiles"]) == {"decode", "balanced", "prefill"}
    assert report["profiles"]["decode"]["workload"]["max_tokens"] == 512
    assert report["profiles"]["balanced"]["workload"]["max_tokens"] == 128
    assert report["profiles"]["prefill"]["workload"]["prompt_words"] == 2048
    for profile in report["profiles"].values():
        assert profile["selected_concurrency"] == 2
        assert profile["confirmation"]["effective_decode_tps"]["p90"] is not None
