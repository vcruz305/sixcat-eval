"""challenge-v2: a harder, opt-in 120-item selection (`--profile challenge-v2`).

Why a separate module: the v1 benchmark is content-addressed. Its manifest
hashes the v1 scorer sources (run.py, selection.py, tools.py, ...) and that
fingerprint is what the community registry approves. Editing those files would
orphan every saved v1 receipt, so v2 lives entirely in new files and leaves the
v1 fingerprint byte-for-byte unchanged. `tests/test_challenge_v2.py` pins that.

What changes relative to challenge-v1 (same six categories, 20 items each):

  knowledge  20 ten-option MMLU-Pro questions, chosen for discrimination and
             hand-checked keys (tools/select_v2_knowledge.py)
  math       20 original multi-step problems with code-verified answers
             (tools/build_v2_math.py); GSM8K is saturated
  truth      tinyTruthfulQA MC1 again, but the options are shuffled per item.
             In the source the correct option is always first, and v1 presents
             the source order, so "always answer A" scores 100 on v1 Truth
  instruct   20 original prompts with stacked constraints, each proven
             satisfiable by a reference answer (tools/build_v2_instruct.py)
  code       20 original function-level problems with brute-force-verified
             tests, including large inputs (tools/build_v2_code.py)
  tools      18 confusable tools, typed/nested arguments, derived values and
             four abstention cases (sixcat/v2_tools.py)

v2 scores are NOT comparable with v1 scores, and v2 is not yet eligible for
Community Results. Difficulty has not been calibrated against a model panel.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .code import _run_humaneval
from .context_preflight import assemble_preflight
from .dataio import DATA, read_jsonl
from .generation import complete_for_item
from .journal import Session, apply_item_gate, run_pending
from .manifest import ATTEMPT_POLICY, SCHEDULE, SCORING_SOURCES, fingerprint
from .parsing import normalize_num, parse_gsm_answer, parse_mc_answer, strip_reasoning
from .receipts import completion_row
from .report import PARSER_VERSION, RESULT_SCHEMA
from .runtime import deadline_scope
from .scheduler import balanced_order, execute_tasks, segment_receipt
from .score import CATEGORIES, category_score, category_stats, overall_score, suite_speed
from .v2_instruct import failed_constraints, item_ok_v2
from .v2_tools import ITEMS_V2, TOOLS_V2, tool_answer_ok_v2

PROFILE = "challenge-v2"
STANDARD_LIMIT = 20
LETTERS = "ABCDEFGHIJKLMNOP"

V2_DATASETS = ("v2_knowledge.jsonl", "v2_math.jsonl", "tiny_truthfulqa.jsonl",
               "v2_instruct.jsonl", "v2_code.jsonl")
V2_SCORING_SOURCES = SCORING_SOURCES + ("challenge_v2.py", "v2_instruct.py", "v2_tools.py")

# tinyTruthfulQA rows, ranked by number of answer options (more distractors
# first, ties by row index). Three rows are skipped: 7 (the "Haslam" item whose
# key docs/eval-run-findings.md already records as noise) and 56 / 57, which
# duplicate or near-duplicate rows 20 / 38.
TRUTH_V2_INDICES = (45, 62, 98, 43, 51, 10, 12, 5, 18, 59, 70, 2, 11, 20, 38, 78, 91, 17, 28, 37)

MC_SUFFIX = "Reply with only the letter of the correct option."
MATH_SUFFIX = ("\n\nGive the final answer as a plain number with no units and no currency symbol. "
               "End with #### <number> and nothing after.")
CODE_HEADER = (
    "Write a complete, correct and efficient Python 3 implementation of the function below. "
    "Output only the code, in a single block.\n"
    "Rules: import only from bisect, collections, fractions, functools, heapq, itertools, math, "
    "operator, re, string and typing. Do not read input, print, or touch files. Do not use "
    "attributes that begin with an underscore or any double-underscore names. Apart from imports, "
    "constants, functions and classes there must be no top-level code. The recursion limit cannot "
    "be raised, so avoid deep recursion. Hidden tests include large inputs and a time limit of a "
    "few seconds.\n\n"
)

_SELECTION_PAYLOAD = {
    "profile": PROFILE,
    "knowledge": "mmlu-pro-reviewed-20",
    "math": "sixcat-generated-20",
    "truth": {"indices": TRUTH_V2_INDICES, "shuffle": "sha256-per-key"},
    "instruct": "sixcat-stacked-20",
    "code": "sixcat-original-20",
    "tools": "typed-nested-abstain-v2",
}
SELECTION_FINGERPRINT_V2 = hashlib.sha256(
    json.dumps(_SELECTION_PAYLOAD, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()[:12]


# --------------------------------------------------------------------------- selection

def check_limit(limit: int | None) -> int:
    if limit is None:
        raise ValueError(f"{PROFILE} has exactly {STANDARD_LIMIT} items per category; --full is not available")
    if not 1 <= limit <= STANDARD_LIMIT:
        raise ValueError(f"{PROFILE} supports --limit 1..{STANDARD_LIMIT}")
    return limit


def catalog(limit: int | None = STANDARD_LIMIT, skip_code_exec: bool = False) -> dict[str, list[tuple[str, Any]]]:
    """Every selected item as (journal key, payload), in presentation order per category."""
    count = check_limit(limit)
    truth_rows = read_jsonl("tiny_truthfulqa.jsonl")
    return {
        "knowledge": [(item["key"], item) for item in read_jsonl("v2_knowledge.jsonl")[:count]],
        "math": [(f"math2:{item['key']}", item) for item in read_jsonl("v2_math.jsonl")[:count]],
        "truth": [(f"tqa2:{index}", truth_rows[index]) for index in TRUTH_V2_INDICES[:count]],
        "instruct": [(f"instruct2:{item['key']}", item) for item in read_jsonl("v2_instruct.jsonl")[:count]],
        "code": [] if skip_code_exec else [(item["task_id"], item) for item in read_jsonl("v2_code.jsonl")[:count]],
        "tools": [(f"tool2:{name}", (name, want, prompt)) for name, want, prompt in ITEMS_V2[:count]],
    }


def selected_keys_v2(limit: int | None = STANDARD_LIMIT, skip_code_exec: bool = False) -> dict[str, list[str]]:
    return {cat: [key for key, _ in rows] for cat, rows in catalog(limit, skip_code_exec).items()}


def expected_counts_v2(limit: int | None = STANDARD_LIMIT, skip_code_exec: bool = False) -> dict[str, int]:
    return {cat: len(keys) for cat, keys in selected_keys_v2(limit, skip_code_exec).items()}


def benchmark_manifest_v2(limit: int | None = STANDARD_LIMIT, skip_code_exec: bool = False) -> dict:
    root = Path(__file__).resolve().parent

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()

    manifest = {
        "version": "sixcat-manifest-v1", "selection_profile": PROFILE,
        "selected_keys": selected_keys_v2(limit, skip_code_exec),
        "data_sha256": {name: digest(DATA / name) for name in V2_DATASETS},
        "scorer_sha256": {name: digest(root / name) for name in V2_SCORING_SOURCES},
        "tools_sha256": fingerprint({"schema": TOOLS_V2, "items": ITEMS_V2}),
    }
    return {**manifest, "fingerprint": fingerprint(manifest)}


# --------------------------------------------------------------------------- pure graders

def presentation_order(key: str, n_choices: int) -> list[int]:
    """Deterministic per-item permutation of option indices; identical on every platform."""
    return sorted(range(n_choices),
                  key=lambda index: hashlib.sha256(f"{PROFILE}|{key}|{index}".encode("utf-8")).hexdigest())


def mc_prompt(stem: str, choices: list[str]) -> str:
    lines = [stem, ""]
    lines += [f"{LETTERS[i]}. {choice}" for i, choice in enumerate(choices)]
    lines += ["", MC_SUFFIX]
    return "\n".join(lines)


def mc_view(category: str, key: str, item: dict[str, Any]) -> tuple[str, str, int, list[int]]:
    """Prompt, gold letter, option count and source-index order for a multiple-choice item."""
    choices = list(item["choices"])
    answer = int(item["answer"])
    if category == "truth":
        order = presentation_order(key, len(choices))
    else:
        order = list(range(len(choices)))     # knowledge: published order (options cross-reference letters)
    shown = [choices[index] for index in order]
    return mc_prompt(item["question"], shown), LETTERS[order.index(answer)], len(shown), order


def grade_mc(text: str, n_choices: int, gold: str) -> dict[str, Any]:
    try:
        parsed = parse_mc_answer(text or "", valid_letters=LETTERS[:n_choices])
    except TypeError:
        # v1 parser raises on an empty answer when valid_letters is set; an empty answer is a miss.
        parsed = {"value": None, "confidence": "low", "status": "unparsed"}
    pred = parsed["value"] or ""
    return {"ok": pred == gold, "pred": pred, "gold": gold,
            "parse_confidence": parsed["confidence"], "parse_status": parsed["status"]}


_HASH_DECORATION = re.compile(r"####\s*(?:\\?\$|USD\s)\s*")


def grade_math(text: str, answer: str) -> dict[str, Any]:
    cleaned = _HASH_DECORATION.sub("#### ", strip_reasoning(text or ""))
    parsed = parse_gsm_answer(cleaned)
    gold = normalize_num(str(answer))
    pred = parsed["value"]
    return {"ok": pred is not None and pred == gold, "pred": pred, "gold": gold,
            "parse_confidence": parsed["confidence"], "parse_status": parsed["status"]}


def math_prompt(item: dict[str, Any]) -> str:
    return item["question"] + MATH_SUFFIX


def code_prompt(item: dict[str, Any]) -> str:
    return CODE_HEADER + item["prompt"]


def grade_code(item: dict[str, Any], text: str) -> bool:
    return _run_humaneval(item["prompt"], text or "", item["test"], item["entry_point"])


# --------------------------------------------------------------------------- runners

def _budget(budgets: dict[str, int], category: str) -> int:
    return int(budgets[category])


def _gate(session: Session | None, category: str, rows: list[dict], items: list[tuple[str, Any]]):
    pending = []
    for key, payload in items:
        action = apply_item_gate(session, category, key, rows)
        if action == "stop":
            return None
        if action == "run":
            pending.append((key, (key, payload)))
    return pending


def _run_mc(category: str, client, items, session, budgets) -> list[dict]:
    rows: list[dict] = []
    pending = _gate(session, category, rows, items)
    if pending is None:
        return rows
    max_tokens = _budget(budgets, category)

    def work(payload):
        key, item = payload
        prompt, gold, n_choices, order = mc_view(category, key, item)
        out = dict(complete_for_item(client, prompt, max_tokens=max_tokens))
        out["prompt"] = prompt
        out["raw_text"] = out["text"] or ""
        verdict = grade_mc(out["text"] or "", n_choices, gold)
        out["parse_confidence"] = verdict["parse_confidence"]
        out["parse_status"] = verdict["parse_status"]
        return completion_row(out, ok=verdict["ok"], pred=verdict["pred"], gold=gold, choice_order=order,
                              grader={"name": "mc-letter-v2", "options": n_choices})

    run_pending(session, category, pending, work, rows)
    return rows


def _run_math(client, items, session, budgets) -> list[dict]:
    rows: list[dict] = []
    pending = _gate(session, "math", rows, items)
    if pending is None:
        return rows
    max_tokens = _budget(budgets, "math")

    def work(payload):
        _, item = payload
        prompt = math_prompt(item)
        out = dict(complete_for_item(client, prompt, max_tokens=max_tokens))
        out["prompt"] = prompt
        out["raw_text"] = out["text"] or ""
        verdict = grade_math(out["text"] or "", item["answer"])
        out["parse_confidence"] = verdict["parse_confidence"]
        out["parse_status"] = verdict["parse_status"]
        return completion_row(out, ok=verdict["ok"], pred=verdict["pred"], gold=verdict["gold"],
                              grader={"name": "exact-number-v2", "tier": item.get("tier"), "topic": item.get("topic")})

    run_pending(session, "math", pending, work, rows)
    return rows


def _run_instruct(client, items, session, budgets) -> list[dict]:
    rows: list[dict] = []
    pending = _gate(session, "instruct", rows, items)
    if pending is None:
        return rows
    max_tokens = _budget(budgets, "instruct")

    def work(payload):
        _, item = payload
        out = dict(complete_for_item(client, item["prompt"], max_tokens=max_tokens))
        text = strip_reasoning(out["text"] or "")
        out["text"] = text
        out["parse_confidence"] = "not_applicable"
        return completion_row(
            out, ok=item_ok_v2(item, text), pred=text[:120], prompt=item["prompt"],
            instruction_id_list=copy.deepcopy(item["instruction_id_list"]), kwargs=copy.deepcopy(item["kwargs"]),
            grader={"name": "instruct-v2", "item_key": item["key"], "failed": failed_constraints(item, text)})

    run_pending(session, "instruct", pending, work, rows)
    return rows


def _run_code(client, items, session, budgets) -> list[dict]:
    rows: list[dict] = []
    pending = _gate(session, "code", rows, items)
    if pending is None:
        return rows
    max_tokens = _budget(budgets, "code")

    def work(payload):
        key, item = payload
        out = dict(complete_for_item(client, code_prompt(item), max_tokens=max_tokens))
        out["text"] = strip_reasoning(out["text"] or "")
        out["parse_confidence"] = "not_applicable"
        return completion_row(
            out, ok=grade_code(item, out["text"]), pred=out["text"][:200], task_id=key,
            entry_point=item["entry_point"], reasoning_content=out.get("reasoning_content") or "",
            grader={"name": "guarded-python-v2", "dataset": "v2_code.jsonl", "task_id": key,
                    "entry_point": item["entry_point"]})

    run_pending(session, "code", pending, work, rows)
    return rows


def _run_tools(client, items, session, budgets) -> list[dict]:
    rows: list[dict] = []
    pending = _gate(session, "tools", rows, items)
    if pending is None:
        return rows
    max_tokens = _budget(budgets, "tools")

    def work(payload):
        _, (name, want, prompt) = payload
        out = dict(complete_for_item(client, prompt, max_tokens=max_tokens, tools=TOOLS_V2))
        out["text"] = strip_reasoning(out["text"] or "")
        out["parse_confidence"] = "not_applicable"
        ok, pred = tool_answer_ok_v2(want, out.get("tool_calls") or [], out["text"])
        return completion_row(
            out, ok=ok, pred=pred, gold=want, prompt=prompt, tool_calls=copy.deepcopy(out.get("tool_calls") or []),
            reasoning_content=out.get("reasoning_content") or "",
            grader={"name": "structured-tool-call-v2", "item": name})

    run_pending(session, "tools", pending, work, rows)
    return rows


def run_battery_v2(client, limit: int | None = STANDARD_LIMIT, session: Session | None = None, *,
                   skip_code_exec: bool = False, configured_ctx: int | None = None) -> dict:
    """challenge-v2 counterpart of run.run_battery; same receipt shape, different content."""
    from .client import fetch_server_props
    from .policy import probe_policy
    from .run import build_overall_flags, continuation_offer

    items = catalog(limit, skip_code_exec)
    budgets = dict(client.policy.budgets)
    with deadline_scope(session.budget.deadline if session is not None else None):
        server_props = getattr(client, "server_props", None)
        if server_props is None:
            server_props = fetch_server_props(client.base_url, client.api_key)
        probe = probe_policy(client)
    probe_failed = probe.get("status") != "ok"
    if probe_failed:
        if session is None:
            raise RuntimeError(f"policy probe failed: {probe.get('reason', 'unknown failure')}")
        session.stopped = session.budget.expired()
        session.errors.append({"phase": "preflight", "status": "deadline" if session.stopped else "error"})
        print("PREFLIGHT FAILED: no scored requests will be sent", flush=True)
    expected = {cat: len(rows) for cat, rows in items.items()}
    preflight = assemble_preflight(
        requested_model=client.model, server_props=server_props, probe=probe,
        n_items=sum(expected.values()), output_reserve=max(budgets.values()) if budgets else 1024,
        configured_ctx=configured_ctx, thinking=bool(client.policy.thinking),
        cache_key=f"{client.base_url}|{client.model}|chat", store_cache=True)
    if session is not None:
        session.collecting = True
    packs = {
        "knowledge": _run_mc("knowledge", client, items["knowledge"], session, budgets),
        "math": _run_math(client, items["math"], session, budgets),
        "truth": _run_mc("truth", client, items["truth"], session, budgets),
        "instruct": _run_instruct(client, items["instruct"], session, budgets),
        "code": _run_code(client, items["code"], session, budgets),
        "tools": _run_tools(client, items["tools"], session, budgets),
    }
    diagnostics = segment = None
    if session is not None:
        session.collecting = False
        if not probe_failed:
            execute_tasks(balanced_order(session.pending_tasks), session)
        latest = {cat: [row for category, key in session.plan_keys if category == cat
                        if (row := session.journal.get(cat, key)) is not None] for cat in CATEGORIES}
        for cat in CATEGORIES:
            keys = [key for category, key in session.plan_keys if category == cat]
            packs[cat] = [row for row in (session.journal.first(cat, key) for key in keys) if row is not None]
        if session.retry_mode in {"failed", "incomplete"} or any(
                len(session.journal.attempts_for(cat, key)) > 1 for cat, key in session.plan_keys):
            latest_scores = {cat: category_score(rows) for cat, rows in latest.items()}
            diagnostics = {"label": "latest-attempt diagnostic; NOT pass@1",
                           "attempt_policy": "latest-attempt-diagnostic",
                           "latest_items": latest, "categories": latest_scores,
                           "overall": overall_score(latest_scores)
                           if any(v is not None for v in latest_scores.values()) else None}
        segment = segment_receipt(session, session.segment_attempts)
        session.journal.append_event({"_sixcat_segment": segment})
    cats = {cat: category_score(rows) for cat, rows in packs.items()}
    stats = {cat: category_stats(rows) for cat, rows in packs.items()}
    timed_out = bool(session and session.stopped)
    overall_flags = build_overall_flags(stats)
    if skip_code_exec:
        overall_flags.append("code-exec-disabled")
    manifest = benchmark_manifest_v2(limit, skip_code_exec)
    result = {
        "model": client.model,
        "artifact_id": getattr(client, "artifact_id", None),
        "server_identity": getattr(client, "server_identity", None),
        "attempt_policy": ATTEMPT_POLICY,
        "schedule": SCHEDULE if session is not None else "category-order",
        "concurrency": session.concurrency if session is not None else 1,
        "performance_calibration": copy.deepcopy(getattr(client, "performance_calibration", None)),
        "benchmark_manifest": manifest,
        "benchmark_fingerprint": manifest["fingerprint"],
        "expected_n": expected,
        "diagnostics": diagnostics,
        "execution": segment,
        "errors": copy.deepcopy(session.errors) if session is not None else [],
        "base_url": client.base_url,
        "request_timeout_seconds": getattr(client, "timeout", None),
        "server_props": server_props,
        "preflight": preflight,
        "policy": client.policy.to_dict(),
        "policy_source": client.policy.source,
        "policy_probe": probe["status"],
        "policy_probe_details": probe,
        "policy_fingerprint": client.policy.fingerprint,
        "budgets": budgets,
        "parser": PARSER_VERSION,
        "code_execution": "disabled" if skip_code_exec else "host-guarded",
        "result_schema": RESULT_SCHEMA,
        "transport": getattr(client, "transport", "openai"),
        "limit": limit,
        "limit_scope": "per_category",
        "selection_profile": PROFILE,
        "selection_fingerprint": SELECTION_FINGERPRINT_V2,
        "timed_out": timed_out,
        "categories": cats,
        "stats": stats,
        "overall": {"policy": client.policy.name,
                    "score": overall_score(cats) if any(v is not None for v in cats.values()) else None},
        "overall_label": f"overall[{client.policy.name}]",
        "overall_flags": overall_flags,
        "n": {cat: len(rows) for cat, rows in packs.items()},
        "items": packs,
        "speed": suite_speed(packs),
    }
    result["complete"] = result["n"] == result["expected_n"] and not timed_out and not probe_failed
    result["speed"]["coverage"] = f"{result['speed']['items']}/{sum(result['n'].values())}"
    if not result["complete"]:
        result["overall_flags"].append("incomplete-scope")
    if session is not None:
        result["execution_segments"] = [event["_sixcat_segment"] for event in session.journal.events
                                        if "_sixcat_segment" in event]
    offer = continuation_offer(result)
    if session is not None and (session.retry_mode or session.retry_keys or session.rescored):
        offer.update(session.continuation_receipt())
    result["continuation"] = offer
    return result


# --------------------------------------------------------------------------- offline regrade

def regrade_v2(document: dict) -> dict:
    """Re-score the saved first responses of a challenge-v2 result. No model calls."""
    from .report import normalise_result
    from .run import build_overall_flags, continuation_offer

    if document.get("selection_profile") != PROFILE:
        raise ValueError(f"not a {PROFILE} result")
    if document.get("attempt_policy") != ATTEMPT_POLICY:
        raise ValueError("offline rescore requires known first-response provenance")
    skip_code = document.get("code_execution") == "disabled"
    manifest = benchmark_manifest_v2(document.get("limit"), skip_code)
    old_manifest = document.get("benchmark_manifest") or {}
    for field in ("data_sha256", "tools_sha256", "selected_keys"):
        if old_manifest.get(field) != manifest[field]:
            raise ValueError(f"cannot regrade: source {field} differs from the installed benchmark")
    items = {cat: dict(rows) for cat, rows in catalog(document.get("limit"), skip_code).items()}
    result = copy.deepcopy(document)
    for cat in CATEGORIES:
        for row in result["items"][cat]:
            key = str(row.get("key") or row.get("id"))
            item = items[cat][key]
            text = strip_reasoning(str(row.get("source_text", row.get("raw_text")) or ""))
            row["previous_verdict"] = {"ok": row["ok"], "parser": document["parser"]}
            row["raw_text"] = text
            if cat in {"knowledge", "truth"}:
                _, gold, n_choices, _ = mc_view(cat, key, item)
                verdict = grade_mc(text, n_choices, gold)
                row.update(ok=verdict["ok"], pred=verdict["pred"], gold=gold,
                           parse_confidence=verdict["parse_confidence"])
            elif cat == "math":
                verdict = grade_math(text, item["answer"])
                row.update(ok=verdict["ok"], pred=verdict["pred"], gold=verdict["gold"],
                           parse_confidence=verdict["parse_confidence"])
            elif cat == "instruct":
                row.update(ok=item_ok_v2(item, text), pred=text[:120], parse_confidence="not_applicable")
            elif cat == "code":
                row.update(ok=grade_code(item, text), pred=text[:200], parse_confidence="not_applicable")
            else:
                ok, pred = tool_answer_ok_v2(item[1], row.get("tool_calls") or [], text)
                row.update(ok=ok, pred=pred, gold=item[1], parse_confidence="not_applicable")
    result["parser"] = PARSER_VERSION
    result["benchmark_manifest"] = manifest
    result["benchmark_fingerprint"] = manifest["fingerprint"]
    result["categories"] = {cat: category_score(rows) for cat, rows in result["items"].items()}
    result["stats"] = {cat: category_stats(rows) for cat, rows in result["items"].items()}
    result["overall"]["score"] = overall_score(result["categories"]) if any(
        value is not None for value in result["categories"].values()) else None
    result["overall_flags"] = build_overall_flags(result["stats"])
    if not result["complete"]:
        result["overall_flags"].append("incomplete-scope")
    if result["code_execution"] == "disabled":
        result["overall_flags"].append("code-exec-disabled")
    result["diagnostics"] = None
    result["execution"] = None
    result["execution_segments"] = []
    result["speed"] = suite_speed(result["items"])
    result["speed"]["origin"] = "original saved generations; no new inference was performed"
    result["continuation"] = continuation_offer(result)
    return normalise_result(result)
