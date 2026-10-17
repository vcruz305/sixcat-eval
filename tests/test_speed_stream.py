"""Deterministic streaming measurements; no model or external requests."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest

from sixcat.policy import Policy, strict_policy
from sixcat.speed_stream import _policy_payload, _sample_from_stream, _stream_one

DONE = "data: [DONE]\n\n"


def event(value):
    return "data: " + json.dumps(value) + "\n\n"


def output(content=None, *, reasoning=None, finish=None, usage=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    value = {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        value["usage"] = usage
    return event(value)


def usage_event(prompt=100, completion=11, *, reasoning=None, **extra):
    usage = {"prompt_tokens": prompt, "completion_tokens": completion}
    if reasoning is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning}
    return event({"choices": [], "usage": usage, **extra})


def client(*, thinking=True, options=None, extra=None):
    data = strict_policy().to_dict()
    data["thinking"] = thinking
    data["extra"].update(extra or {})
    return SimpleNamespace(
        base_url="https://sixcat-test.invalid/v1", model="fixture-model",
        api_key="none", timeout=30, policy=Policy(**data),
        speed_options=dict(options or {}),
    )


class Clock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now

    def advance(self, amount):
        self.now += amount


class TimedStream(httpx.AsyncByteStream):
    def __init__(self, clock, events, *, close_delay=0.0):
        self.clock, self.events = clock, events
        self.close_delay, self.closed = close_delay, False

    async def __aiter__(self):
        for delay, value in self.events:
            self.clock.advance(delay)
            if isinstance(value, Exception):
                raise value
            yield value.encode("utf-8") if isinstance(value, str) else value

    async def aclose(self):
        if not self.closed:
            self.closed = True
            self.clock.advance(self.close_delay)


def measure(events, *, thinking=True, options=None, close_delay=0.0, capabilities=None):
    async def run():
        clock, calls = Clock(), []
        async def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                stream=TimedStream(clock, events, close_delay=close_delay),
            )
        with mock.patch("sixcat.speed_stream.time.perf_counter", side_effect=clock):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                sample = await _stream_one(
                    http, client(thinking=thinking, options=options),
                    "private prompt sentinel", max_tokens=256,
                    timeout_s=30, capabilities=capabilities,
                )
        return sample, calls
    return asyncio.run(run())


@pytest.mark.parametrize("thinking", [True, False])
def test_explicit_thinking_wins_over_preclose_and_preserves_frozen_effort(thinking):
    fixture = client(thinking=thinking, extra={"preclose_think": True, "reasoning_effort": "high"})
    payload = _policy_payload(fixture, "test", 256)
    assert payload["chat_template_kwargs"]["enable_thinking"] is thinking
    assert payload["chat_template_kwargs"]["reasoning_effort"] == "high"
    assert payload["reasoning_effort"] == "high"
    assert "preclose_think" not in payload
    assert payload["max_tokens"] == 256
    assert fixture.policy.extra["preclose_think"] is True


def sample(*, usage=None, timings=None, meta_info=None, **extra):
    return _sample_from_stream(
        started=10.0, first_output=11.0, last_output=12.0, ended=15.0,
        first_answer=11.0, usage=usage or {}, timings=timings or {}, metrics={},
        meta_info=meta_info or {}, chunks=4, content_chunks=2,
        compatibility_mode="include_usage", thinking_requested=False, **extra,
    )


@pytest.mark.parametrize("value", [-1, 1.5, float("nan"), float("inf"), True, "11"])
def test_counts_must_be_finite_nonnegative_integers(value):
    result = sample(usage={"prompt_tokens": value, "completion_tokens": value})
    assert result["prompt_tokens"] is None
    assert result["completion_tokens"] is None
    assert result["effective_prefill_tps"] is None
    assert result["effective_decode_tps"] is None


def test_native_count_fallback_preserves_cache_and_independent_rates():
    result = sample(timings={
        "prompt_n": 20, "cache_n": 80, "predicted_n": 11,
        "prompt_per_second": 300, "predicted_per_second": 75,
    })
    assert result["prompt_tokens"] == 100
    assert result["cached_prompt_tokens"] == 80
    assert result["completion_tokens"] == 11
    assert result["token_count_source"] == "native_timings"
    assert result["server_prefill_tps"] == 300
    assert result["server_decode_tps"] == 75


@pytest.mark.parametrize("details", [
    {"reasoning_tokens": 12}, {"reasoning_tokens": 8, "answer_tokens": 9},
])
def test_inconsistent_reasoning_counts_suppress_client_rates(details):
    result = sample(
        usage={"prompt_tokens": 100, "completion_tokens": 11, "completion_tokens_details": details},
        timings={"predicted_per_second": 75},
    )
    assert result["effective_prefill_tps"] is None
    assert result["effective_decode_tps"] is None
    assert result["server_decode_tps"] == 75


def test_decode_ends_at_last_content_excluding_usage_and_cleanup():
    result, _ = measure([
        (1, output("first")), (1, output(" last")),
        (3, usage_event(reasoning=0)), (0, DONE),
    ], close_delay=1)
    assert result["ok"]
    assert result["client_ttft_s"] == pytest.approx(1)
    assert result["e2e_s"] == pytest.approx(2)
    assert result["stream_end_s"] == pytest.approx(6)
    assert result["effective_decode_tps"] == pytest.approx(10)
    assert result["tpot_s"] == pytest.approx(.1)
    assert result["effective_prefill_tps"] == pytest.approx(100)
    assert result["content_chunks"] == 2


def test_streamed_reasoning_has_distinct_first_answer_time():
    result, _ = measure([
        (1, output(reasoning="work")), (1, output(reasoning=" more")),
        (1, output("answer")), (1, output(" end", finish="stop")),
        (1, usage_event(completion=21, reasoning=15)), (0, DONE),
    ])
    assert result["ok"]
    assert result["reasoning_observation"] == "streamed"
    assert result["client_ttft_s"] == 1
    assert result["client_ttfo_s"] == 3
    assert result["reasoning_tokens"] == 15
    assert result["answer_tokens"] == 6
    assert result["effective_decode_tps"] == pytest.approx(20 / 3)


def test_reported_hidden_reasoning_preserves_native_metrics():
    result, _ = measure([
        (3, output("answer")), (1, output(" end")),
        (0, usage_event(
            completion=21, reasoning=15,
            timings={"prompt_per_second": 300, "predicted_per_second": 75},
            metrics={"time_to_first_token_ms": 100, "generation_time_ms": 1000},
        )), (0, DONE),
    ])
    assert result["ok"]
    assert result["reasoning_observation"] == "hidden_reported"
    assert result["client_ttfo_s"] == 3
    assert result["effective_prefill_tps"] is None
    assert result["effective_decode_tps"] is None
    assert result["decode_metric_status"] == "hidden_reasoning"
    assert result["server_prefill_tps"] == 300
    assert result["server_decode_tps"] == 75
    assert result["provider_ttft_s"] == pytest.approx(.1)
    assert result["provider_effective_decode_tps"] == pytest.approx(20)


def test_declared_hidden_visibility_is_not_claimed_observed():
    result, _ = measure([
        (3, output("answer")), (1, output(" end")), (0, usage_event()), (0, DONE),
    ], options={"reasoning_visibility": "hidden"})
    assert result["ok"]
    assert result["reasoning_observation"] == "unverified"
    assert not result["hidden_reasoning_reported"]
    assert result["reasoning_visibility_declared"] == "hidden"
    assert result["client_ttfo_s"] == 3
    assert result["effective_prefill_tps"] is None
    assert result["effective_decode_tps"] is None


def test_unverified_preopened_reasoning_cap_does_not_invent_answer_time():
    result, _ = measure([
        (1, output("Let me think")), (1, output(" carefully", finish="length")),
        (0, usage_event(completion=256)), (0, DONE),
    ])
    assert result["ok"] and result["thinking_requested"] and result["output_limit_reached"]
    assert result["reasoning_observation"] == "unverified"
    assert result["client_ttfo_s"] is None
    assert result["first_answer_s"] is None
    assert result["ttfo_metric_status"] == "unverified_answer_boundary"
    assert result["effective_decode_tps"] is not None
    assert result["decode_metric_status"] == "unverified_reasoning_visibility"


def test_explicit_off_plain_answer_time_is_still_qualified():
    result, _ = measure([
        (1, output("answer")), (1, output(" end")), (0, usage_event()), (0, DONE),
    ], thinking=False)
    assert not result["thinking_requested"]
    assert result["client_ttfo_s"] == 1
    assert result["reasoning_observation"] == "unverified"


@pytest.mark.parametrize("prefix", [
    [(1, output("<thi")), (1, output("nk>reason")), (1, output(" more</th")), (1, output("ink>answer"))],
    [(1, output("reason")), (1, output(" more")), (1, output("</thi")), (1, output("nk>answer"))],
])
def test_split_think_markers_and_preopened_templates_identify_answer(prefix):
    result, _ = measure(prefix + [
        (1, output(" end")), (0, usage_event(completion=31)), (0, DONE),
    ])
    assert result["ok"]
    assert result["reasoning_observation"] == "streamed"
    assert result["client_ttft_s"] == 1
    assert result["client_ttfo_s"] == 4
    assert result["content_chunks"] == 5


def test_cumulative_usage_corrects_first_chunk_n_minus_k():
    result, _ = measure([
        (1, output("three tokens", usage={
            "prompt_tokens": 100, "completion_tokens": 3,
            "completion_tokens_details": {"reasoning_tokens": 0},
        })),
        (1, output("remaining")), (3, usage_event(completion=11, reasoning=0)), (0, DONE),
    ])
    assert result["ok"]
    assert result["first_chunk_tokens"] == 3
    assert not result["first_chunk_count_is_approximate"]
    assert result["first_chunk_token_source"] == "usage.completion_tokens_cumulative"
    assert result["effective_decode_tps"] == pytest.approx(8)


def test_single_buffered_chunk_cannot_establish_decode():
    result, _ = measure([
        (1, output("all output", finish="stop")),
        (3, usage_event(completion=100, reasoning=0)), (0, DONE),
    ])
    assert result["ok"]
    assert result["content_chunks"] == 1
    assert result["decode_metric_status"] == "buffered_output"
    assert result["effective_decode_tps"] is None


@pytest.mark.parametrize("tail", [
    [(0, "data: {not-json}\n\n")],
    [(0, 'data: {"choices": [')],
    [(0, event({"error": {"message": "private failure sentinel"}}))],
    [(0, event({"error": {}}))],
    [(0, 'event: error\ndata: {"message":"failed"}\n\n')],
    [(0, event({"choices": "invalid"}))],
    [(0, event({"choices": [{"delta": 123}]}))],
    [(0, event({"choices": [{"delta": {"content": 123}}]}))],
    [],
    [(0, output(finish="content_filter")), (0, DONE)],
])
def test_malformed_errored_or_unfinished_streams_are_failures(tail):
    result, _ = measure([(1, output("partial"))] + tail)
    assert not result["ok"]
    assert result["error"] is not None
    assert result["effective_decode_tps"] is None
    assert "private failure sentinel" not in json.dumps(result)


@pytest.mark.parametrize("ending, limited", [
    ([(0, DONE)], False),
    ([(0, output(finish="stop"))], False),
    ([(0, output(finish="length"))], True),
    ([(0, output(finish="stop")), (0, DONE)], False),
])
def test_valid_finish_or_done_is_sufficient_completion(ending, limited):
    result, _ = measure([
        (1, output("first")), (1, output(" last")), (0, usage_event(reasoning=0)),
    ] + ending)
    assert result["ok"] and result["generation_completed"]
    assert result["output_limit_reached"] is limited


def test_reasoning_only_length_completion_has_no_answer():
    result, _ = measure([
        (1, output(reasoning="work")), (1, output(reasoning=" more", finish="length")),
        (0, usage_event(completion=256, reasoning=256)), (0, DONE),
    ])
    assert result["ok"] and result["output_limit_reached"]
    assert result["client_ttfo_s"] is None
    assert result["answer_tokens"] == 0


def test_later_output_after_finish_is_rejected():
    result, _ = measure([
        (1, output("first", finish="stop")), (1, output("unexpected later output")), (0, DONE),
    ])
    assert not result["ok"]
    assert result["error"] == "output_after_finish"


def test_transport_failure_after_partial_output_raises():
    with pytest.raises(httpx.RemoteProtocolError):
        measure([(1, output("partial")), (1, httpx.RemoteProtocolError("truncated transport"))])


def test_private_content_is_not_persisted():
    result, _ = measure([
        (1, output(reasoning="private reasoning sentinel")),
        (1, output("private answer sentinel")),
        (0, usage_event(completion=11, reasoning=5)), (0, DONE),
    ])
    serialized = json.dumps(result)
    for text in ("private prompt sentinel", "private reasoning sentinel", "private answer sentinel"):
        assert text not in serialized


def test_multiline_sse_and_heartbeats_do_not_count_as_output():
    multiline = 'data: {\ndata: "choices": [{"delta": {"content": "first"}, "finish_reason": null}]\ndata: }\n\n'
    result, _ = measure([
        (.5, ": heartbeat\n\n"), (.5, output()),
        (1, multiline), (1, output(" last", finish="stop")),
        (0, usage_event(reasoning=0)), (0, DONE),
    ])
    assert result["ok"]
    assert result["content_chunks"] == 2
    assert result["client_ttft_s"] == 2


@pytest.mark.parametrize("continuous", [False, True])
def test_supported_option_fallback_is_narrow_and_cached(continuous):
    async def run():
        calls, caps, clock = [], {"per_chunk_usage": continuous}, Clock()
        async def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            options = body.get("stream_options", {})
            reject = options.get("continuous_usage_stats") if continuous else "stream_options" in body
            if reject:
                field = "continuous_usage_stats" if continuous else "stream_options"
                return httpx.Response(422, json={"error": {"message": "Unsupported " + field}})
            return httpx.Response(200, stream=TimedStream(clock, [
                (1, output("first")), (1, output(" last")),
                (0, usage_event(reasoning=0)), (0, DONE),
            ]))
        with mock.patch("sixcat.speed_stream.time.perf_counter", side_effect=clock):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                for _ in range(2):
                    result = await _stream_one(
                        http, client(), "fixture", max_tokens=256, timeout_s=30, capabilities=caps,
                    )
                    assert result["ok"]
        assert len(calls) == 3
        for body in calls[1:]:
            if continuous:
                assert body["stream_options"] == {"include_usage": True}
            else:
                assert "stream_options" not in body
    asyncio.run(run())


@pytest.mark.parametrize("status", [400, 422])
def test_unrelated_bad_request_is_never_retried(status):
    async def run():
        calls = []
        async def handler(request):
            calls.append(request)
            return httpx.Response(status, json={
                "error": {"param": "reasoning_effort", "message": "Unsupported reasoning_effort"},
                "request": {"stream_options": {"include_usage": True}},
            })
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(httpx.HTTPStatusError):
                await _stream_one(http, client(), "fixture", max_tokens=256, timeout_s=30)
        assert len(calls) == 1
    asyncio.run(run())


def test_option_negotiation_shares_one_absolute_deadline():
    async def run():
        calls = []
        class DelayedOutput(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield output("first").encode()
                await asyncio.sleep(.04)
                yield output("last", finish="stop").encode()
                yield DONE.encode()
        async def handler(request):
            calls.append(request)
            if len(calls) == 1:
                await asyncio.sleep(.04)
                return httpx.Response(400, json={"error": {"message": "Unsupported stream_options"}})
            return httpx.Response(200, stream=DelayedOutput())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(TimeoutError):
                await _stream_one(http, client(), "fixture", max_tokens=256, timeout_s=.06, capabilities={})
        assert 1 <= len(calls) <= 2
    asyncio.run(run())
