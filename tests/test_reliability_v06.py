from __future__ import annotations

import copy
import io
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from sixcat.analysis import paired_comparison
from sixcat.client import ChatClient
from sixcat.dataio import read_jsonl
from sixcat.journal import RunJournal, Session, TimeBudget
from sixcat.manifest import ATTEMPT_POLICY, benchmark_manifest, expected_counts, fingerprint, observed_server_identity
from sixcat.policy import strict_policy
from sixcat.report import ResultFormatError, RunScopeMismatchError, compare_results, normalise_result
from sixcat.run import run_battery
from sixcat.runtime import deadline_scope
from sixcat.scheduler import Task, balanced_order, execute_tasks, segment_receipt
from sixcat.score import CATEGORIES, extract_gsm_number_conf, extract_mc_letter_conf, parse_mc_answer
from sixcat.tools import ITEMS, _tool_answer_ok


@contextmanager
def endpoint(*, delay=.01, drip=False):
    """Real loopback HTTP, no API key, GPU, paid service, or external traffic."""
    state = {"active": 0, "max_active": 0, "starts": [], "requests": []}
    lock = threading.Lock()
    code = {"Complete the following Python function. Output only code.\n\n" + item["prompt"]: item["canonical_solution"]
            for item in read_jsonl("humaneval.jsonl")}
    tools = {prompt: expected for _, expected, prompt in ITEMS}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def json_reply(self, value):
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/props":
                self.json_reply({"n_ctx": 32768, "chat_template": "fixture"})
            else:
                self.json_reply({"data": [{"id": "fixture", "max_model_len": 32768}]})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
                state["starts"].append(time.monotonic())
                state["requests"].append(payload)
            try:
                if drip:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    for _ in range(100):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(.02)
                    return
                time.sleep(delay)
                prompt = payload["messages"][0]["content"]
                text = code.get(prompt, "391" if "17 multiplied by 23" in prompt else "A")
                if "End with ####" in prompt:
                    text = "#### 0"
                calls = []
                if prompt in tools:
                    expected = tools[prompt]
                    if expected is None:
                        text = "56"
                    else:
                        text = ""
                        calls = [{"id": f"call-{i}", "type": "function", "function":
                                  {"name": name, "arguments": json.dumps(arguments)}}
                                 for i, (name, arguments) in enumerate(expected)]
                self.json_reply({"model": "fixture", "system_fingerprint": "fixture-runtime",
                    "choices": [{"message": {"content": text, "tool_calls": calls}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 6,
                              "completion_tokens_details": {"reasoning_tokens": 2}},
                    "timings": {"prompt_per_second": 100, "predicted_per_second": 50}})
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with lock:
                    state["active"] -= 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def run_fixture(path: Path, url: str, *, concurrency=4, limit=20, seconds=20, retry=None):
    client = ChatClient(url, "fixture", strict_policy(), timeout=10)
    with RunJournal(path, identity={"parser": "v5", "attempt_policy": ATTEMPT_POLICY}) as journal:
        session = Session(journal, TimeBudget(seconds), concurrency=concurrency,
                          retry_mode=retry, retry_failed=retry == "failed", include_remaining=retry != "failed")
        result = run_battery(client, limit=limit, session=session)
    return result


@pytest.fixture
def complete_result(tmp_path):
    with endpoint(delay=.001) as (url, state):
        result = run_fixture(tmp_path / "complete.jsonl", url, limit=1)
    assert result["complete"]
    return result


def test_real_http_120_questions_and_all_six_receipts(tmp_path):
    with endpoint() as (url, state):
        result = run_fixture(tmp_path / "run.jsonl", url)
    assert result["n"] == {cat: 20 for cat in CATEGORIES}
    assert result["complete"] is True
    assert len(state["requests"]) == 121
    assert 2 <= state["max_active"] <= 4
    assert result["categories"]["tools"] == 100
    assert result["categories"]["code"] == 100
    assert result["speed"]["coverage"] == "120/120"
    assert result["execution"]["responses"] == 120
    assert result["execution"]["completion_tokens"] == 720
    for cat in CATEGORIES:
        assert len(result["items"][cat]) == len(set(r["key"] for r in result["items"][cat]))
        for row in result["items"][cat]:
            assert row["wall_s"] > 0
            assert row["ctok"] == 6 and row["rtok"] == 2 and row["atok"] == 4
            assert row["provider_model"] == "fixture"
            assert row["wire_request"]["model"] == "fixture"
    normalise_result(result)


def test_scheduler_preserves_ranks_and_balances_categories():
    tasks = [Task(cat, f"{cat}:{i}", None, lambda _: {}, []) for cat in CATEGORIES for i in range(20)]
    ordered = balanced_order(tasks)
    assert [t.cat for t in ordered[:6]] == list(CATEGORIES)
    for cat in CATEGORIES:
        assert [t.key for t in ordered if t.cat == cat] == [f"{cat}:{i}" for i in range(20)]


def test_no_queued_start_after_deadline(tmp_path):
    starts = []
    budget = TimeBudget(10)
    def work(i):
        starts.append(i)
        if i == 0:
            budget.seconds = 0
        return {"ok": True}
    with RunJournal(tmp_path / "deadline.jsonl") as journal:
        session = Session(journal, budget, concurrency=4)
        tasks = [Task("math", str(i), i, work, []) for i in range(120)]
        execute_tasks(tasks, session)
    assert starts == [0]
    assert session.stopped


def test_slow_drip_is_bound_by_total_deadline():
    with endpoint(drip=True) as (url, _):
        client = ChatClient(url, "fixture", strict_policy(), timeout=.12)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            client.complete("slow response")
        assert time.monotonic() - started < .8


def test_deadline_limits_each_active_request(tmp_path):
    with endpoint(delay=.4) as (url, state):
        with patch("sixcat.run.probe_policy", return_value={"status": "ok"}):
            started = time.monotonic()
            result = run_fixture(tmp_path / "partial.jsonl", url, seconds=.15)
            elapsed = time.monotonic() - started
    assert elapsed < 1.5
    assert not result["complete"] and result["timed_out"]
    assert len(state["requests"]) <= 4
    assert sum(result["n"].values()) == 0
    assert result["errors"]


def test_retry_changes_diagnostic_not_headline(tmp_path):
    with endpoint(delay=.001) as (url, _):
        path = tmp_path / "retry.jsonl"
        first = run_fixture(path, url, limit=1)
        with RunJournal(path) as journal:
            failed = next((cat, rows[0]["key"]) for cat, rows in first["items"].items() if not rows[0]["ok"])
            cat, key = failed
            journal.append({**journal.get(cat, key), "ok": True})
        second = run_fixture(path, url, limit=1)
    assert first["overall"] == second["overall"]
    assert second["diagnostics"]["overall"] > second["overall"]["score"]
    assert second["execution"]["completion_tokens"] == 0
    assert len(second["execution_segments"]) == 2
    compare_results(first, second)


def test_first_response_survives_failure_retry_and_infra_attempt(tmp_path):
    path = tmp_path / "immutable.jsonl"
    with RunJournal(path) as journal:
        journal.append({"cat": "math", "key": "gsm:1", "ok": None, "scored": False, "status": "error"})
        journal.append({"cat": "math", "key": "gsm:1", "ok": False})
        journal.append({"cat": "math", "key": "gsm:1", "ok": True})
        assert journal.first("math", "gsm:1")["ok"] is False
        row = journal.first("math", "gsm:1")
        row["ok"] = True
        assert journal.first("math", "gsm:1")["ok"] is False
    with RunJournal(path) as journal:
        assert journal.first("math", "gsm:1")["ok"] is False
        assert journal.get("math", "gsm:1")["ok"] is True
        assert len(journal.attempts_for("math", "gsm:1")) == 3


@pytest.mark.parametrize("tail", [b'{"cat": "math",', b'\xe2\x82'])
def test_torn_tail_does_not_swallow_next_record(tmp_path, tail):
    path = tmp_path / "torn.jsonl"
    path.write_bytes(b'{"cat":"math","key":"1","ok":true}\n' + tail)
    with pytest.warns(RuntimeWarning, match="torn journal"):
        with RunJournal(path) as journal:
            journal.append({"cat": "math", "key": "2", "ok": False})
    with RunJournal(path) as journal:
        assert len(journal.done_keys()) == 2
    assert list(tmp_path.glob("*.torn-*.bin"))[0].read_bytes() == tail


def test_complete_last_record_missing_newline_and_interior_corruption(tmp_path):
    path = tmp_path / "journal.jsonl"
    path.write_text('{"cat":"math","key":"1","ok":true}', encoding="utf-8")
    with RunJournal(path) as journal:
        journal.append({"cat": "math", "key": "2", "ok": True})
    assert len(path.read_text().splitlines()) == 2
    path.write_text('broken\n{"cat":"math","key":"1","ok":true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt journal"):
        RunJournal(path)
    path.write_text('', encoding='utf-8')
    with RunJournal(path):
        pass


def test_single_writer_lock_and_atomic_summary(tmp_path):
    from sixcat.storage import atomic_write_json
    path = tmp_path / "locked.jsonl"
    with RunJournal(path):
        with pytest.raises(ValueError, match="active writer"):
            RunJournal(path, resume=False)
    result = tmp_path / "result.json"
    atomic_write_json(result, {"old": True})
    with patch("sixcat.storage.os.replace", side_effect=OSError("fixture")):
        with pytest.raises(OSError):
            atomic_write_json(result, {"new": True})
    assert json.loads(result.read_text()) == {"old": True}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("text,value", [("The answer is definitely B.", "B"),
    ("The answer is ambiguous.", None), ("I'm not sure.", None),
    ("<think>The answer is B", None), ("Answer is P", "P"),
    ("Answer is B. Answer is C.", None)])
def test_mc_parser_regressions(text, value):
    assert extract_mc_letter_conf(text)[0] == value


def test_mc_choice_range_and_status():
    assert parse_mc_answer("P", valid_letters="ABCD")["value"] is None
    assert parse_mc_answer("Answer is B. Answer is C.")["status"] == "ambiguous"


@pytest.mark.parametrize("text,value", [("#### 1/2", "0.5"), ("#### 1/0", None),
    ("#### 1+2", None), ("#### 1e3", "1000"), ("#### 000.50", ".5"),
    ("<think>Answer is 42", None), ("#### 1,234.00", "1234")])
def test_math_parser_regressions(text, value):
    actual = extract_gsm_number_conf(text)[0]
    assert actual == ("0.5" if value == ".5" else value)


def test_tools_reject_boolean_number_confusion():
    expected = [("add", {"a": 100, "b": 1})]
    def calls(b):
        return [{"function": {"name": "add", "arguments": json.dumps({"a": 100, "b": b})}}]
    assert _tool_answer_ok(expected, calls(True), "")[0] is False
    assert _tool_answer_ok(expected, calls(1.0), "")[0] is True
    assert _tool_answer_ok(expected, calls("1"), "")[0] is False


def test_stdio_timeout_poisons_connection_and_expired_budget_sends_nothing():
    gate = threading.Event()
    class Stalled:
        def readline(self, size):
            gate.wait(2)
            return '{"text":"late"}\n'
    out = io.StringIO()
    client = ChatClient("stdio://harness", "fixture", strict_policy(), timeout=.03,
                        transport="stdio", stdio_in=Stalled(), stdio_out=out)
    try:
        with pytest.raises(TimeoutError):
            client.complete("one")
        with pytest.raises(RuntimeError, match="desynchronized"):
            client.complete("two")
        assert len(out.getvalue().splitlines()) == 1
        fresh_out = io.StringIO()
        fresh = ChatClient("stdio://harness", "fixture", strict_policy(), timeout=1,
                           transport="stdio", stdio_in=Stalled(), stdio_out=fresh_out)
        with deadline_scope(time.monotonic() - 1), pytest.raises(TimeoutError):
            fresh.complete("already expired")
        assert not fresh_out.getvalue()
    finally:
        gate.set()


def test_resume_endpoint_and_hermes_upstream_identity():
    a = {"base_url": "http://127.0.0.1:8085/v1", "model": "m"}
    b = {**a, "base_url": "http://localhost:9000/v1"}
    assert "base_url" in RunJournal.identity_changes(a, b)
    assert not RunJournal._is_loopback_base_url("http://localhost.example.invalid")
    upstream = {"provider": "p", "model": "m", "route_fingerprint": "same"}
    assert not RunJournal.identity_changes({**a, "verified_upstream": upstream}, {**b, "verified_upstream": upstream})
    assert RunJournal.identity_changes({**a, "artifact_id": "Q4"}, {**a, "artifact_id": "Q3"})
    observed = observed_server_identity({"openai_models": {"data": [{"id": "other", "max_model_len": 42}]}}, "m")
    assert observed == {"evidence": "unavailable"}


def test_scope_counts_and_content_manifest():
    assert sum(expected_counts(20).values()) == 120
    assert sum(expected_counts(None).values()) == 884
    assert sum(expected_counts(None, True).values()) == 720
    assert sum(expected_counts(50).values()) == 270
    manifest = benchmark_manifest(20)
    assert len(manifest["fingerprint"]) == 64
    assert len(manifest["selected_keys"]["code"]) == 20
    changed = copy.deepcopy(manifest)
    changed["data_sha256"]["tiny_gsm8k.jsonl"] = "changed"
    assert fingerprint({k: v for k, v in changed.items() if k != "fingerprint"}) != manifest["fingerprint"]


@pytest.mark.parametrize("mutation", ["overall", "duplicate", "nonfinite", "count", "manifest"])
def test_result_integrity_rejects_inconsistency(complete_result, mutation):
    result = copy.deepcopy(complete_result)
    if mutation == "overall": result["overall"]["score"] += 1
    if mutation == "duplicate": result["items"]["tools"] *= 2
    if mutation == "nonfinite": result["categories"]["truth"] = float("nan")
    if mutation == "count": result["expected_n"]["math"] = 30
    if mutation == "manifest": result["benchmark_manifest"]["selected_keys"]["math"] = []
    with pytest.raises(ResultFormatError):
        normalise_result(result)


def test_paired_changes_and_seeded_bootstrap(complete_result):
    b = copy.deepcopy(complete_result)
    row = b["items"]["math"][0]
    row["ok"] = not row["ok"]
    first = paired_comparison(complete_result, b, samples=100, seed=9)
    second = paired_comparison(complete_result, b, samples=100, seed=9)
    assert first == second
    assert len(first["changes"]) == 1
    same = paired_comparison(complete_result, complete_result, samples=100)
    assert same["degenerate"] and same["delta_points"] == 0
    b["benchmark_fingerprint"] = "different"
    with pytest.raises(RunScopeMismatchError):
        compare_results(complete_result, b)


def test_offline_rescore_export_and_source_immutability(complete_result):
    from sixcat.offline import regrade, export_evalplus
    before = copy.deepcopy(complete_result)
    with patch("sixcat.client.open_request", side_effect=AssertionError("must not contact any endpoint")):
        rescored = regrade(complete_result)
        samples = export_evalplus(complete_result)
    assert rescored["overall"] == complete_result["overall"]
    assert rescored["execution"] is None
    assert len(samples) == 1 and samples[0]["task_id"] == "HumanEval/145"
    assert complete_result == before
    with pytest.raises(ValueError, match="source data_sha256"):
        altered = copy.deepcopy(complete_result)
        altered["benchmark_manifest"]["data_sha256"] = {}
        regrade(altered)


def test_current_segment_throughput_does_not_sum_overlapping_latency(tmp_path):
    with RunJournal(tmp_path / "speed.jsonl") as journal:
        session = Session(journal, TimeBudget(None), concurrency=4)
        receipt = segment_receipt(session, [{"ctok": 100, "wall_s": 10}] * 4, elapsed=10)
    assert receipt["throughput_tps"] == 40


def test_cli_validation_no_requests_on_invalid_destination(tmp_path):
    from sixcat.__main__ import main
    path = str(tmp_path / "same.jsonl")
    with patch("sixcat.client.open_request", side_effect=AssertionError("unexpected HTTP")):
        with pytest.raises(SystemExit):
            main(["--model", "m", "--out", path, "--log", path])
        with pytest.raises(SystemExit):
            main(["--model", "m", "--max-minutes", "nan"])
        with pytest.raises(SystemExit):
            main(["repeat", "--seeds", "1,1", "--out-dir", str(tmp_path), "--", "--model", "m"])


def test_grading_interruption_reuses_the_returned_completion(tmp_path):
    from sixcat.generation import complete_for_item
    from sixcat.receipts import completion_row
    class Client:
        calls = 0
        def complete(self, prompt, **kwargs):
            self.calls += 1
            return {"text": "original wrong answer", "usage": {"completion_tokens": 4}, "wall_s": .1}
    client = Client()
    path = tmp_path / "deferred.jsonl"
    def failed_grader(_):
        complete_for_item(client, "same prompt")
        raise TimeoutError("local grader interrupted")
    with RunJournal(path) as journal:
        session = Session(journal, TimeBudget(None))
        execute_tasks([Task("code", "HumanEval/1", None, failed_grader, [])], session)
        assert not journal.done_keys()
        assert journal.attempts_for("code", "HumanEval/1")[0]["deferred_response"]["text"] == "original wrong answer"
    def successful_grader(_):
        out = complete_for_item(client, "same prompt")
        return completion_row(out, ok=False)
    with RunJournal(path) as journal:
        session = Session(journal, TimeBudget(None))
        rows = []
        execute_tasks([Task("code", "HumanEval/1", None, successful_grader, rows)], session)
        assert rows[0]["ok"] is False and rows[0]["generation_reused"]
        assert not session.segment_attempts
    assert client.calls == 1


def test_repeat_series_is_explicit_and_uses_distinct_fresh_seeds(tmp_path):
    from sixcat.__main__ import main
    with endpoint(delay=.001) as (url, state):
        rc = main(["repeat", "--seeds", "11,12", "--out-dir", str(tmp_path / "repeat"),
                   "--max-minutes", "1", "--", "--model", "fixture", "--base-url", url,
                   "--limit", "1", "--concurrency", "4"])
    assert rc == 0
    summary = json.loads((tmp_path / "repeat" / "repeat.json").read_text())
    assert summary["complete_runs"] == 2
    assert {r["seed"] for r in summary["runs"]} == {11, 12}
    assert len(state["requests"]) == 14
    assert {r["seed"] for r in state["requests"]} == {11, 12}


def test_preflight_timeout_produces_partial_receipt(tmp_path):
    from sixcat.__main__ import main
    output = tmp_path / "preflight.json"
    with endpoint(delay=.3) as (url, _):
        rc = main(["--model", "fixture", "--base-url", url, "--limit", "1",
                   "--max-minutes", ".001", "--out", str(output)])
    assert rc == 2
    result = json.loads(output.read_text())
    assert not result["complete"] and sum(result["n"].values()) == 0
    assert result["policy_probe"] == "failed"
    normalise_result(result)


def test_status_first_attempt_does_not_count_errors_or_segment_events(tmp_path):
    from tests.test_hermes_skill import _load_script
    path = tmp_path / "status.jsonl"
    with RunJournal(path, identity={"parser": "v5", "attempt_policy": ATTEMPT_POLICY}) as journal:
        journal.append({"cat": "math", "key": "gsm:1", "ok": False})
        journal.append({"cat": "math", "key": "gsm:1", "ok": True})
        journal.append({"cat": "math", "key": "gsm:2", "ok": None, "scored": False})
        journal.append_event({"_sixcat_segment": {"elapsed_s": 1}})
    summary = _load_script("status.py").summarize_journal(path)
    assert summary["rows"] == 1 and summary["failed"] == 1
