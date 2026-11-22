"""challenge-v2: content integrity, graders, and a real-HTTP end-to-end run.

No model, GPU, API key or external network is used. The "oracle" endpoint
answers from the shipped keys and references, which proves every one of the 120
items can be passed by a response that the harness itself grades.
"""
from __future__ import annotations

import ast
import copy
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sixcat import challenge_v2 as v2
from sixcat.__main__ import main as cli_main
from sixcat.client import ChatClient
from sixcat.community import SubmissionError, load_registry, validate_result
from sixcat.dataio import read_jsonl
from sixcat.journal import RunJournal, Session, TimeBudget
from sixcat.manifest import ATTEMPT_POLICY, benchmark_manifest, expected_counts
from sixcat.policy import strict_policy
from sixcat.report import RunScopeMismatchError, compare_results, normalise_result
from sixcat.run import run_battery
from sixcat.score import CATEGORIES
from sixcat.v2_instruct import V2_INSTRUCTION_IDS, check_v2, failed_constraints, item_ok_v2, unfence
from sixcat.v2_tools import ITEMS_V2, TOOLS_V2, canonical_arguments, tool_answer_ok_v2
from tools import build_v2_code, build_v2_instruct, build_v2_math


# --------------------------------------------------------------------------- fixtures

def _oracle() -> dict[str, dict]:
    """prompt -> the response a perfect model would give."""
    answers: dict[str, dict] = {}
    items = v2.catalog()
    for category in ("knowledge", "truth"):
        for key, item in items[category]:
            prompt, gold, _, _ = v2.mc_view(category, key, item)
            answers[prompt] = {"text": gold}
    for _, item in items["math"]:
        answers[v2.math_prompt(item)] = {"text": f"Working...\n#### {item['answer']}"}
    references = build_v2_instruct.references()
    for _, item in items["instruct"]:
        answers[item["prompt"]] = {"text": references[item["key"]]}
    for _, item in items["code"]:
        answers[v2.code_prompt(item)] = {"text": "```python\n" + item["canonical_solution"] + "```"}
    for _, (_, want, prompt) in items["tools"]:
        if want is None:
            answers[prompt] = {"text": "Could you tell me a bit more?"}
        else:
            answers[prompt] = {"text": "", "calls": [
                {"id": f"call-{i}", "type": "function",
                 "function": {"name": name, "arguments": json.dumps(arguments)}}
                for i, (name, arguments) in enumerate(want)]}
    return answers


@contextmanager
def endpoint(mode: str = "oracle"):
    """Loopback OpenAI-compatible server. mode: oracle | always_a | empty."""
    oracle = _oracle()
    state = {"requests": []}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, value):
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/props":
                self.reply({"n_ctx": 32768, "chat_template": "fixture"})
            else:
                self.reply({"data": [{"id": "fixture", "max_model_len": 32768}]})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                state["requests"].append(payload)
            prompt = payload["messages"][0]["content"]
            answer = {"text": "391"}
            if prompt in oracle:
                if mode == "oracle":
                    answer = oracle[prompt]
                elif mode == "always_a":
                    answer = {"text": "A"}
                else:
                    answer = {"text": ""}
            self.reply({"model": "fixture", "system_fingerprint": "fixture-runtime",
                        "choices": [{"message": {"content": answer["text"], "tool_calls": answer.get("calls", [])},
                                     "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 6}})

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


def run_v2(path, url, *, limit=20, concurrency=4):
    client = ChatClient(url, "fixture", strict_policy(), timeout=20)
    with RunJournal(path, identity={"parser": "v5", "attempt_policy": ATTEMPT_POLICY}) as journal:
        session = Session(journal, TimeBudget(120), concurrency=concurrency)
        return v2.run_battery_v2(client, limit=limit, session=session)


@pytest.fixture(scope="module")
def oracle_result(tmp_path_factory):
    with endpoint("oracle") as (url, state):
        result = run_v2(tmp_path_factory.mktemp("v2") / "oracle.jsonl", url)
    result["_requests"] = len(state["requests"])
    return result


# --------------------------------------------------------------------------- v1 must not move

def test_v1_benchmark_fingerprint_is_still_the_approved_one():
    """Adding v2 must not change a single byte that the v1 manifest hashes."""
    assert benchmark_manifest(20)["fingerprint"] in load_registry()["benchmarks"]


def test_v2_scope_matches_v1_counts_for_every_supported_limit():
    for limit in range(1, v2.STANDARD_LIMIT + 1):
        assert v2.expected_counts_v2(limit) == expected_counts(limit)
        assert v2.expected_counts_v2(limit, True) == expected_counts(limit, True)
    assert sum(v2.expected_counts_v2().values()) == 120
    for bad in (None, 0, 21):
        with pytest.raises(ValueError):
            v2.check_limit(bad)


def test_v2_manifest_is_distinct_and_hashes_its_own_sources():
    manifest = v2.benchmark_manifest_v2()
    assert manifest["selection_profile"] == "challenge-v2"
    assert manifest["fingerprint"] != benchmark_manifest(20)["fingerprint"]
    assert set(manifest["data_sha256"]) == set(v2.V2_DATASETS)
    assert {"challenge_v2.py", "v2_instruct.py", "v2_tools.py", "parsing.py"} <= set(manifest["scorer_sha256"])
    assert all(len(set(keys)) == len(keys) == 20 for keys in manifest["selected_keys"].values())
    assert manifest["fingerprint"] not in load_registry()["benchmarks"]


# --------------------------------------------------------------------------- shipped data

def test_generated_data_files_match_their_builders():
    assert build_v2_math.main(["--check"]) == 0
    assert build_v2_instruct.main(["--check"]) == 0
    assert build_v2_code.main(["--check"]) == 0


def test_math_rows_are_well_formed_and_parse_as_their_own_answers():
    rows = read_jsonl("v2_math.jsonl")
    assert [row["key"] for row in rows] == [f"m{i:02d}" for i in range(1, 21)]
    assert sorted(row["tier"] for row in rows) == sorted([1, 2, 3, 4] * 5)
    for row in rows:
        assert v2.grade_math(f"#### {row['answer']}", row["answer"])["ok"]
        assert not v2.grade_math("#### 0.123", row["answer"])["ok"]


def test_knowledge_rows_have_ten_distinct_options_and_a_valid_key():
    rows = read_jsonl("v2_knowledge.jsonl")
    assert len(rows) == 20 and len({row["key"] for row in rows}) == 20
    for row in rows:
        assert row["key"].startswith("mmlupro:")
        assert len(row["choices"]) == 10 == len(set(row["choices"]))
        assert all(choice == choice.strip() and choice for choice in row["choices"])
        assert 0 <= row["answer"] < 10


def test_truth_selection_is_valid_and_shuffles_the_key_off_position_a():
    rows = read_jsonl("tiny_truthfulqa.jsonl")
    assert len(set(v2.TRUTH_V2_INDICES)) == 20 and 7 not in v2.TRUTH_V2_INDICES
    golds = []
    for key, item in v2.catalog()["truth"]:
        prompt, gold, n_choices, order = v2.mc_view("truth", key, item)
        assert sorted(order) == list(range(len(item["choices"]))) and n_choices == len(order)
        assert item["choices"][int(item["answer"])] in prompt
        assert f"{gold}. {item['choices'][int(item['answer'])]}" in prompt
        golds.append(gold)
    assert all(int(rows[i]["answer"]) == 0 for i in v2.TRUTH_V2_INDICES)   # the v1 weakness
    assert golds.count("A") <= 3 and len(set(golds)) >= 6
    # Pinned: a change here silently changes every saved v2 Truth prompt.
    assert "".join(golds) == "LCIJFCFHFBGCBEDDDEBA"


def test_presentation_order_is_deterministic():
    assert v2.presentation_order("tqa2:45", 12) == v2.presentation_order("tqa2:45", 12)
    assert v2.presentation_order("tqa2:45", 12) != v2.presentation_order("tqa2:62", 12)


def test_instruct_rows_use_only_implemented_constraints_and_are_satisfiable():
    from sixcat.instruct import SUPPORTED_INSTRUCTION_IDS

    references = build_v2_instruct.references()
    rows = read_jsonl("v2_instruct.jsonl")
    assert len(rows) == 20
    used = set()
    for row in rows:
        assert len(row["instruction_id_list"]) == len(row["kwargs"]) >= 1
        for inst_id in row["instruction_id_list"]:
            assert inst_id in V2_INSTRUCTION_IDS or inst_id in SUPPORTED_INSTRUCTION_IDS
            used.add(inst_id)
        assert item_ok_v2(row, references[row["key"]]), row["key"]
        assert not item_ok_v2(row, "") and not item_ok_v2(row, "I cannot help with that.")
    # No shipped item depends on language detection, so verdicts cannot drift with langdetect.
    assert not used & {"change_case:english_lowercase", "change_case:english_capital", "language:response_language"}


def test_code_rows_compile_and_every_reference_passes_the_guarded_runner():
    rows = read_jsonl("v2_code.jsonl")
    assert [row["task_id"] for row in rows] == [f"sixcat-v2/{i:02d}" for i in range(1, 21)]
    for row in rows:
        ast.parse(row["prompt"])
        ast.parse(row["test"])
        assert f"def {row['entry_point']}(" in row["prompt"]
        assert v2.grade_code(row, "```python\n" + row["canonical_solution"] + "```"), row["task_id"]
        stub = row["prompt"] + "    return None\n"
        assert not v2.grade_code(row, stub), row["task_id"]


def test_tool_items_are_consistent_with_the_tool_schema():
    schema = {tool["function"]["name"]: tool["function"]["parameters"] for tool in TOOLS_V2}
    assert len(schema) == len(TOOLS_V2) == 18 and len(ITEMS_V2) == 20
    assert len({name for name, _, _ in ITEMS_V2}) == 20
    assert sum(1 for _, want, _ in ITEMS_V2 if want is None) == 4
    for name, want, prompt in ITEMS_V2:
        assert prompt.strip()
        for tool_name, arguments in want or []:
            parameters = schema[tool_name]
            assert set(parameters["required"]) <= set(arguments) <= set(parameters["properties"]), name
            for key, value in arguments.items():
                enum = parameters["properties"][key].get("enum")
                assert enum is None or value in enum, (name, key)


# --------------------------------------------------------------------------- graders

def test_empty_multiple_choice_answer_is_a_miss_not_a_crash():
    for text in ("", "   ", "<think>hmm"):
        verdict = v2.grade_mc(text, 10, "C")
        assert verdict["ok"] is False and verdict["pred"] == ""
    assert v2.grade_mc("C", 10, "C")["ok"]
    assert v2.grade_mc("The answer is J.", 10, "J")["ok"]
    assert not v2.grade_mc("K", 10, "C")["ok"]            # outside the displayed options


@pytest.mark.parametrize("text,ok", [
    ("#### 525.22", True), ("so the total is\n#### $525.22", True), ("#### \\$525.22", True),
    ("#### 525.220", True), ("#### 525.2", False), ("The answer is 525.22", True), ("#### 525,22", False),
    ("", False), ("#### five hundred", False),
])
def test_math_grader_accepts_plain_numbers_and_currency_decoration(text, ok):
    assert v2.grade_math(text, "525.22")["ok"] is ok


def test_math_grader_handles_thousands_separators_and_integers():
    assert v2.grade_math("#### 1,877", "1877")["ok"]
    assert v2.grade_math("#### 1877.0", "1877")["ok"]
    assert not v2.grade_math("#### 1878", "1877")["ok"]


def _call(name, arguments):
    return {"type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def test_tool_grader_defaults_paths_types_order_and_abstention():
    want = dict((name, w) for name, w, _ in ITEMS_V2)
    listing = want["recursive glob"]
    assert tool_answer_ok_v2(listing, [_call("list_directory", {"path": "./src/core/", "recursive": True, "pattern": "*.rs"})], "")[0]
    assert not tool_answer_ok_v2(listing, [_call("list_directory", {"path": "src/core", "pattern": "*.rs"})], "")[0]
    event = want["event in utc"]
    args = dict(event[0][1])
    assert tool_answer_ok_v2(event, [_call("create_event", {**args, "reminder_minutes": 10})], "")[0]     # explicit default
    assert not tool_answer_ok_v2(event, [_call("create_event", {**args, "reminder_minutes": 15})], "")[0]
    assert not tool_answer_ok_v2(event, [_call("create_event", {**args, "start": "2026-03-12T14:30:00+00:00"})], "")[0]
    quiet = want["cancel quietly then find"]
    calls = [_call(name, arguments) for name, arguments in quiet]
    assert tool_answer_ok_v2(quiet, calls, "")[0]
    assert not tool_answer_ok_v2(quiet, calls[::-1], "")[0]                                                # order matters
    assert not tool_answer_ok_v2(quiet, [_call("cancel_event", {"event_id": "evt_8841", "notify_attendees": "false"}),
                                         calls[1]], "")[0]                                                # string is not a boolean
    assert tool_answer_ok_v2(want["negative value"], [_call("convert_units", {"value": -40.0, "from_unit": "c", "to_unit": "f"})], "")[0]
    assert not tool_answer_ok_v2(want["draft not send"], [_call("send_email", dict(want["draft not send"][0][1]))], "")[0]
    assert tool_answer_ok_v2(None, [], "Which room and when?")[0]
    assert not tool_answer_ok_v2(None, [], "  ")[0]
    assert not tool_answer_ok_v2(None, [_call("book_room", {"room_id": "A"})], "ok")[0]
    assert canonical_arguments("search_files", {"query": "x", "max_results": 20}) == {"query": "x"}
    assert canonical_arguments("unknown", "not-a-dict") == "not-a-dict"


@pytest.mark.parametrize("inst_id,kwargs,good,bad", [
    ("v2:line_count", {"relation": "exactly", "n": 2}, "a\n\nb", "a\nb\nc"),
    ("v2:line_count", {"relation": "at least", "n": 2}, "a\nb\nc", "a"),
    ("v2:words_per_line", {"relation": "exactly", "n": 2}, "one two\nthree four", "one two\nthree"),
    ("v2:words_per_line", {"relation": "at most", "n": 2}, "one - two\nthree", "one two three"),
    ("v2:word_ladder", {"start": 1, "step": 2}, "a\nb c d\ne f g h i", "a\nb c"),
    ("v2:word_count", {"relation": "exactly", "n": 3}, "one, two -- three!", "one two"),
    ("v2:char_count", {"relation": "at most", "n": 5}, "abcde", "abcdef"),
    ("v2:char_occurrences", {"char": "!", "n": 1}, "wow!", "wow!!"),
    ("v2:forbidden_chars", {"chars": "0123456789"}, "no digits", "route 66"),
    ("v2:no_uppercase", {}, "all lower 12", "Mixed case"),
    ("v2:no_lowercase", {}, "ALL UPPER 12", "Mixed CASE"),
    ("v2:acrostic", {"word": "cat"}, "Calm\n- Able\ntrue", "calm\nable"),
    ("v2:alliteration", {"letter": "s"}, "Seven silly 'snakes' sing.", "seven big snakes"),
    ("v2:unique_words", {}, "Each word here differs", "the cat saw The dog"),
    ("v2:max_word_length", {"n": 4}, "tiny word list, okay?", "tiny words"),
    ("v2:nth_word", {"n": 2, "word": "First"}, "The first, then", "first the"),
    ("v2:line_endings", {"suffix": "."}, "One.\nTwo.", "One.\nTwo"),
    ("v2:line_starts", {"prefix": "RULE"}, "RULE 1\nRULE 2", "RULE 1\nrule 2"),
    ("v2:alternating_prefixes", {"prefixes": ["A:", "B:"]}, "A: hi\nB: yo\nA: ok", "A: hi\nA: yo"),
    ("v2:line_regex", {"pattern": "[A-Z][a-z]+\\|[0-9]{2}"}, "Ada|41\nBen|33", "Ada|41\nben|33"),
    ("v2:alphabetical_lines", {}, "apple x\nBanana y\ncherry z", "pear\napple"),
    ("v2:starts_with", {"text": "Dear Ms. Okafor,"}, "Dear Ms. Okafor,\nHi", "Hello Ms. Okafor,"),
    ("v2:paragraphs", {"n": 2}, "one\nstill one\n\ntwo", "one\n\ntwo\n\nthree"),
    ("v2:required_order", {"terms": ["alpha", "beta"]}, "Alpha then beta then alpha", "beta then alpha"),
    ("v2:integers_sum", {"count": 2, "total": 10}, "4 apples and 6 pears", "4 apples, 6 pears, 0 plums"),
    ("v2:json_object", {"fields": {"n": {"type": "integer", "min": 1, "max": 3},
                                   "tags": {"type": "array", "length": 2, "items": {"type": "string"}, "sorted": True},
                                   "ok": {"type": "boolean"}, "name": {"type": "string", "max_words": 2}}},
     '```json\n{"n": 2, "tags": ["a", "b"], "ok": false, "name": "Two Words"}\n```',
     '{"n": 2, "tags": ["b", "a"], "ok": false, "name": "Two Words"}'),
])
def test_each_v2_constraint_accepts_and_rejects(inst_id, kwargs, good, bad):
    assert check_v2(inst_id, kwargs, good) is True
    assert check_v2(inst_id, kwargs, bad) is False


def test_v2_constraints_fail_closed_and_json_shape_is_strict():
    assert check_v2("v2:unknown", {}, "text") is False
    assert check_v2("v2:line_count", {"relation": "about", "n": 1}, "text") is False
    assert check_v2("v2:line_count", {}, "text") is False
    assert check_v2("v2:line_count", "not-a-dict", "text") is False
    assert check_v2("v2:line_regex", {"pattern": "("}, "text") is False
    assert check_v2("v2:acrostic", {"word": "ab"}, "apple\n---") is False
    assert check_v2("v2:alphabetical_lines", {}, "apple\n...") is False
    fields = {"fields": {"n": {"type": "integer"}, "kind": {"type": "string", "enum": ["a", "b"]}}}
    assert check_v2("v2:json_object", fields, '{"n": 1, "kind": "a"}')
    for wrong in ('{"n": true, "kind": "a"}', '{"n": 1.0, "kind": "a"}', '{"n": 1, "kind": "c"}',
                  '{"n": 1}', '{"n": 1, "kind": "a", "extra": 0}', '[1]', 'Here you go: {"n": 1, "kind": "a"}',
                  '{"n": 1, "kind": ""}'):
        assert not check_v2("v2:json_object", fields, wrong), wrong
    assert not check_v2("v2:json_object", {"fields": {"x": {"type": "array", "length": 1}}}, '{"x": "no"}')
    assert not check_v2("v2:json_object", {"fields": {"x": {"type": "mystery"}}}, '{"x": 1}')
    assert unfence("```\nbody\n```") == "body" and unfence("```only one line") == "```only one line"
    item = {"prompt": "p", "instruction_id_list": ["v2:no_uppercase"], "kwargs": []}
    assert failed_constraints(item, "x") == ["v2:no_uppercase"] and not item_ok_v2(item, "x")
    mixed = {"prompt": "p", "instruction_id_list": ["v2:no_uppercase", "punctuation:no_comma"], "kwargs": [{}, {}]}
    assert item_ok_v2(mixed, "fine") and failed_constraints(mixed, "Not, fine") == ["v2:no_uppercase", "punctuation:no_comma"]


# --------------------------------------------------------------------------- end to end

def test_oracle_scores_120_of_120_over_real_http(oracle_result):
    result = oracle_result
    assert result["selection_profile"] == "challenge-v2"
    assert result["n"] == {cat: 20 for cat in CATEGORIES} == result["expected_n"]
    assert result["complete"] is True and result["_requests"] == 121
    failed = {cat: [row["key"] for row in result["items"][cat] if not row["ok"]] for cat in CATEGORIES}
    assert failed == {cat: [] for cat in CATEGORIES}
    assert result["overall"]["score"] == 100
    assert result["benchmark_fingerprint"] == v2.benchmark_manifest_v2()["fingerprint"]
    document = {key: value for key, value in result.items() if key != "_requests"}
    normalise_result(document)
    for row in result["items"]["truth"]:
        assert sorted(row["choice_order"]) == list(range(len(row["choice_order"])))
    assert all(row["grader"]["failed"] == [] for row in result["items"]["instruct"])


def test_always_a_no_longer_wins_truth(tmp_path):
    with endpoint("always_a") as (url, _):
        result = run_v2(tmp_path / "a.jsonl", url)
    assert result["complete"] is True
    assert result["categories"]["truth"] <= 15            # v1 Truth gives this strategy 100
    assert result["categories"]["math"] == 0 and result["categories"]["code"] == 0
    assert result["categories"]["instruct"] == 0
    assert result["categories"]["tools"] == 20            # only the four abstention items


def test_empty_answers_are_scored_as_failures_not_errors(tmp_path):
    with endpoint("empty") as (url, _):
        result = run_v2(tmp_path / "empty.jsonl", url, limit=3)
    assert result["complete"] is True and not result["errors"]
    assert result["overall"]["score"] == 0
    assert result["n"] == {cat: 3 for cat in CATEGORIES}


def test_v2_and_v1_results_refuse_to_compare_and_v2_is_not_community_eligible(oracle_result, tmp_path):
    document = {key: value for key, value in oracle_result.items() if key != "_requests"}
    table, _ = compare_results(document, copy.deepcopy(document))
    assert "overall" in table
    from tests.test_reliability_v06 import endpoint as v1_endpoint

    with v1_endpoint(delay=.001) as (url, _):
        client = ChatClient(url, "fixture", strict_policy(), timeout=10)
        with RunJournal(tmp_path / "v1.jsonl", identity={"parser": "v5", "attempt_policy": ATTEMPT_POLICY}) as journal:
            v1 = run_battery(client, limit=20, session=Session(journal, TimeBudget(60), concurrency=4))
    assert v1["selection_profile"] == "challenge-v1"
    with pytest.raises(RunScopeMismatchError):
        compare_results(v1, document)
    with pytest.raises(SubmissionError):
        validate_result(document)


def test_offline_regrade_reproduces_and_detects_changed_verdicts(oracle_result):
    document = {key: value for key, value in oracle_result.items() if key != "_requests"}
    again = v2.regrade_v2(document)
    assert again["categories"] == document["categories"] and again["overall"]["score"] == 100
    tampered = copy.deepcopy(document)
    tampered["items"]["math"][0]["raw_text"] = "#### 1"
    tampered["items"]["math"][0].pop("source_text", None)
    tampered["items"]["tools"][0]["tool_calls"] = []
    regraded = v2.regrade_v2(tampered)
    assert regraded["categories"]["math"] == 95 and regraded["categories"]["tools"] == 95
    assert regraded["items"]["math"][0]["previous_verdict"]["ok"] is True
    with pytest.raises(ValueError):
        v2.regrade_v2({**document, "selection_profile": "challenge-v1"})
    stale = copy.deepcopy(document)
    stale["benchmark_manifest"]["data_sha256"]["v2_math.jsonl"] = "changed"
    with pytest.raises(ValueError):
        v2.regrade_v2(stale)
    with pytest.raises(ValueError):
        v2.regrade_v2({**document, "attempt_policy": "legacy"})


def test_run_without_a_session_and_with_code_disabled(tmp_path):
    with endpoint("oracle") as (url, _):
        client = ChatClient(url, "fixture", strict_policy(), timeout=20)
        result = v2.run_battery_v2(client, limit=1, skip_code_exec=True)
    assert result["n"] == {"knowledge": 1, "math": 1, "truth": 1, "instruct": 1, "code": 0, "tools": 1}
    assert result["schedule"] == "category-order" and "code-exec-disabled" in result["overall_flags"]
    assert result["categories"]["code"] is None and result["overall"]["score"] == 100


# --------------------------------------------------------------------------- CLI

def _cli(monkeypatch, argv):
    monkeypatch.setenv("SIXCAT_NO_SUBMISSION_PROMPT", "1")
    return cli_main(argv)


def test_cli_profile_flag_runs_resumes_plans_and_rescores(tmp_path, monkeypatch, capsys):
    out = tmp_path / "v2.json"
    with endpoint("oracle") as (url, state):
        base = ["--base-url", url, "--model", "fixture", "--profile", "challenge-v2", "--limit", "2",
                "--concurrency", "2", "--max-minutes", "2", "--out", str(out)]
        assert _cli(monkeypatch, base) == 0
        first_requests = len(state["requests"])
        assert _cli(monkeypatch, base + ["--retry", "remaining"]) == 0      # nothing left: no new scored requests
        assert len(state["requests"]) == first_requests + 1                 # only the unscored policy probe
        # The same journal must not be resumable as a v1 run.
        with pytest.raises(SystemExit):
            _cli(monkeypatch, [arg for arg in base if arg not in {"--profile", "challenge-v2"}])
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["selection_profile"] == "challenge-v2" and saved["overall"]["score"] == 100
    assert saved["n"] == {cat: 2 for cat in CATEGORIES}
    capsys.readouterr()
    assert cli_main(["retry-plan", str(out), "--retry", "failed", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["argv"][-2:] == ["--profile", "challenge-v2"]
    rescored = tmp_path / "v2-rescored.json"
    assert cli_main(["rescore", str(out), "--out", str(rescored)]) == 0
    assert json.loads(rescored.read_text(encoding="utf-8"))["regrade_provenance"]["kind"] == "offline-no-new-generations"
    with pytest.raises(SystemExit):
        cli_main(["rescore", str(out), "--out", str(rescored)])             # never overwrite
    with pytest.raises(SystemExit):
        cli_main(["export-evalplus", str(out), "--out", str(tmp_path / "x.jsonl")])


def test_cli_rejects_unsupported_v2_scopes_and_routes_v1_rescore_unchanged(tmp_path, monkeypatch):
    for extra in (["--full"], ["--limit", "21"]):
        with pytest.raises(SystemExit):
            _cli(monkeypatch, ["--model", "fixture", "--profile", "challenge-v2", *extra])
    from sixcat.v2_cli import result_profile

    missing = tmp_path / "missing.json"
    assert result_profile([str(missing), "--out", "x"]) is None
    assert result_profile(["--out"]) is None
    listed = tmp_path / "list.json"
    listed.write_text("[]", encoding="utf-8")
    assert result_profile([str(listed)]) is None
