from __future__ import annotations

from .generation import complete_for_item

import copy
import time
from .receipts import completion_row
from .runtime import deadline_scope
from .scheduler import balanced_order, execute_tasks, segment_receipt
from .manifest import ATTEMPT_POLICY, SCHEDULE, benchmark_manifest, expected_counts
from typing import Any

from .client import ChatClient, fetch_server_props
from .context_preflight import assemble_preflight, format_preflight
from .code import run_code
from .dataio import read_jsonl
from .instruct import item_ok
from .journal import Session, apply_item_gate, emit, run_pending
from .policy import STRICT_BUDGETS, family_from_source, probe_policy
from .report import PARSER_VERSION, RESULT_SCHEMA
from .score import (
    CATEGORIES,
    answer_tokens,
    category_score,
    category_stats,
    extract_gsm_number_conf,
    extract_mc_letter_conf,
    parse_mc_answer,
    parse_gsm_answer,
    _strip_reasoning,
    is_loop_failure,
    overall_score,
    suite_speed,
)
from .tools import run_tools
from .selection import (
    INSTRUCT_CHALLENGE_INDICES,
    KNOWLEDGE_CHALLENGE_INDICES,
    MATH_CHALLENGE_INDICES,
    SELECTION_FINGERPRINT,
    SELECTION_PROFILE,
    TRUTH_CHALLENGE_INDICES,
    select_by_indices,
    select_indexed_by_indices,
)

# Phase 3 (sixcat v2.1, B3): right-sized from Phase 1's own measured truncation, not
# guessed. At the old defaults (knowledge/truth=32, math=256, instruct=400, code=512,
# tools=128) a live 20-item run showed knowledge truncating 11/80 (~14%) and instruct
# 8/20 (40%) -- both silently scored as wrong answers, not as incomplete. These are the
# "no-think" values; Phase 4 adds a thinking-mode column once the policy layer can toggle
# reasoning on and these need real headroom for a trace (measured up to 553 tokens on math
# alone -- see sixcat-sampling-policy-review-2026-08-20.md).
DEFAULT_BUDGETS = STRICT_BUDGETS

FULL_SCORED_ITEMS = 884
LETTERS = "ABCDEFGHIJKLMNOP"


def expected_scored_items(limit: int | None, *, skip_code_exec: bool = False) -> int:
    """Derive scope from actual selected corpora; Tools caps at 20, not at limit."""
    return sum(expected_counts(limit, skip_code_exec).values())


def continuation_offer(result: dict[str, Any]) -> dict[str, Any]:
    """Describe leftover work that can merge into this receipt without a full rerun."""
    skip_code = result.get("code_execution") == "disabled"
    expected = expected_scored_items(result.get("limit"), skip_code_exec=skip_code)
    scored = sum(int(count or 0) for count in (result.get("n") or {}).values())
    remaining = max(expected - scored, 0)
    failed_keys: list[str] = []
    diagnostic_items = (result.get("diagnostics") or {}).get("latest_items")
    for category, rows in (diagnostic_items or result.get("items") or {}).items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("ok") is True:
                continue
            failed_keys.append(f"{row.get('cat') or category}/{row.get('key') or row.get('id')}")
    return {
        "expected": expected,
        "scored": scored,
        "remaining": remaining,
        "failed": len(failed_keys),
        "failed_keys": failed_keys,
        "timed_out": bool(result.get("timed_out")),
        "can_continue_remaining": remaining > 0,
        "can_retry_failed": bool(failed_keys),
        "merged_rerun": "--retry remaining|failed|incomplete on the same --log/--out",
    }


def retry_plan_from_result(result: dict[str, Any], *, retry: str, result_path: str | None = None) -> dict[str, Any]:
    """Build merge argv from a saved result so a Hermes session can retry without guessing."""
    if retry not in {"failed", "remaining", "incomplete"}:
        raise ValueError(f"unknown retry mode {retry!r}")
    offer = continuation_offer(result)
    policy = result.get("policy") if isinstance(result.get("policy"), dict) else {}
    argv: list[str] = ["--policy", str(policy.get("name") or "custom")]
    if result.get("model"):
        argv.extend(["--model", str(result["model"])])
    if result.get("base_url"):
        argv.extend(["--base-url", str(result["base_url"])])
    for category, value in (result.get("budgets") or {}).items():
        argv.extend(["--budget", f"{category}={value}"])
    if result.get("artifact_id"):
        argv.extend(["--artifact-id", str(result["artifact_id"])])
    argv.extend(["--concurrency", str(result.get("concurrency", 1))])
    if policy.get("name") == "custom":
        if policy.get("temperature") is None:
            raise ValueError("custom result is missing temperature")
        argv.extend(["--temperature", str(policy["temperature"])])
        if policy.get("top_p") is not None:
            argv.extend(["--top-p", str(policy["top_p"])])
        if policy.get("top_k") is not None:
            argv.extend(["--top-k", str(policy["top_k"])])
        if policy.get("min_p") is not None:
            argv.extend(["--min-p", str(policy["min_p"])])
    if policy.get("thinking") is True:
        argv.extend(["--thinking", "on"])
    elif policy.get("thinking") is False:
        argv.extend(["--thinking", "off"])
    extra = policy.get("extra") if isinstance(policy.get("extra"), dict) else {}
    if extra.get("seed") is not None:
        argv.extend(["--seed", str(extra["seed"])])
    source = str(result.get("policy_source") or policy.get("source") or "")
    family = family_from_source(source)
    if family:
        argv.extend(["--policy-family", family])
    if result.get("limit") is None:
        argv.extend(["--full", "--max-minutes", "0"])
    else:
        argv.extend(["--limit", str(result["limit"]), "--max-minutes", "30"])
    timeout = result.get("request_timeout_seconds")
    if timeout:
        argv.extend(["--request-timeout", str(timeout)])
    if result.get("transport", "openai") == "stdio":
        # Journal identity records transport; a retry plan that dropped it
        # could never resume a stdio receipt.
        argv.extend(["--transport", "stdio"])
    if result.get("code_execution") == "disabled":
        argv.append("--skip-code-exec")
    argv.extend(["--retry", retry])
    log_path = result.get("log")
    if log_path:
        argv.extend(["--log", str(log_path)])
    if result_path:
        argv.extend(["--out", str(result_path)])
    return {
        "model": result.get("model"),
        "retry": retry,
        "argv": argv,
        "continuation": offer,
    }


def split_category_limit(limit: int | None, dataset_count: int) -> list[int | None]:
    """Split one category cap fairly across its component datasets."""
    if dataset_count <= 0:
        raise ValueError("dataset_count must be positive")
    if limit is None:
        return [None] * dataset_count
    if limit < 0:
        raise ValueError("limit must be non-negative")
    base, remainder = divmod(limit, dataset_count)
    return [base + (1 if index < remainder else 0) for index in range(dataset_count)]


def choice_letter(i: int) -> str:
    if i < 0 or i >= len(LETTERS):
        raise IndexError(i)
    return LETTERS[i]


def arc_answer_letter(item: dict[str, Any]) -> str:
    """Map ARC's source label to the letter used in Sixcat's presented choices."""
    labels = [str(label) for label in (item.get("labels") or [])]
    answer = str(item.get("answer"))
    texts = item.get("texts")
    if not labels or (texts is not None and len(labels) != len(texts)):
        raise ValueError("ARC labels must align one-to-one with texts")
    try:
        return choice_letter(labels.index(answer))
    except ValueError as exc:
        raise ValueError(f"ARC answer {answer!r} is absent from labels {labels!r}") from exc


def _take(session: Session | None, cat: str, key: str, rows: list[dict]) -> str:
    return apply_item_gate(session, cat, key, rows)


def _emit(session: Session | None, cat: str, key: str, row: dict[str, Any]) -> dict[str, Any]:
    return emit(session, cat, key, row)


def _row(out: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return completion_row(out, **extra)


def _ask_mc(client: ChatClient, stem: str, choices: list[str], max_tokens: int = 32) -> dict[str, Any]:
    lines = [stem, ""]
    for i, c in enumerate(choices):
        lines.append(f"{choice_letter(i)}. {c}")
    lines.append("")
    lines.append("Reply with only the letter of the correct option.")
    out = complete_for_item(client, "\n".join(lines), max_tokens=max_tokens)
    out["prompt"] = "\n".join(lines)
    parsed = parse_mc_answer(out["text"] or "", valid_letters=LETTERS[:len(choices)])
    out["pred"] = parsed["value"] or ""
    out["parse_confidence"] = parsed["confidence"]
    out["parse_status"] = parsed["status"]
    # The complete visible response is the parser receipt. Truncating it here makes a
    # saved verdict impossible to re-derive even when the server completed normally.
    out["raw_text"] = out["text"] or ""
    return out


def run_knowledge(
    client: ChatClient,
    limit: int | None,
    session: Session | None = None,
    budgets: dict[str, int] | None = None,
) -> list[dict]:
    mt = (budgets or DEFAULT_BUDGETS).get("knowledge", DEFAULT_BUDGETS["knowledge"])
    rows: list[dict] = []
    mmlu_limit, arc_limit, hellaswag_limit, winogrande_limit = split_category_limit(limit, 4)
    pending: list[tuple[str, Any]] = []

    def _gate(key: str, payload: Any) -> str:
        action = _take(session, "knowledge", key, rows)
        if action == "run":
            pending.append((key, payload))
        return action

    for i, item in select_indexed_by_indices(read_jsonl("tiny_mmlu.jsonl"), mmlu_limit, KNOWLEDGE_CHALLENGE_INDICES["mmlu"]):
        if _gate(f"mmlu:{i}", ("mmlu", item)) == "stop":
            return rows
    for i, item in select_indexed_by_indices(read_jsonl("tiny_arc.jsonl"), arc_limit, KNOWLEDGE_CHALLENGE_INDICES["arc"]):
        if _gate(f"arc:{i}", ("arc", item)) == "stop":
            return rows
    for i, item in select_indexed_by_indices(
        read_jsonl("tiny_hellaswag.jsonl"), hellaswag_limit, KNOWLEDGE_CHALLENGE_INDICES["hellaswag"]
    ):
        if _gate(f"hellaswag:{i}", ("hellaswag", item)) == "stop":
            return rows
    for i, item in select_indexed_by_indices(
        read_jsonl("tiny_winogrande.jsonl"), winogrande_limit, KNOWLEDGE_CHALLENGE_INDICES["winogrande"]
    ):
        if _gate(f"winogrande:{i}", ("winogrande", item)) == "stop":
            return rows

    def work(payload: Any) -> dict[str, Any]:
        kind, item = payload
        if kind == "mmlu":
            out = _ask_mc(client, item["question"], item["choices"], max_tokens=mt)
            pred = out["pred"]
            gold = choice_letter(int(item["answer"]))
            return _row(out, ok=pred == gold, pred=pred, gold=gold)
        if kind == "arc":
            out = _ask_mc(client, item["question"], item["texts"], max_tokens=mt)
            pred = out["pred"]
            gold = arc_answer_letter(item)
            return _row(out, ok=pred == gold, pred=pred, gold=gold)
        if kind == "hellaswag":
            out = _ask_mc(client, item["ctx"] + "\n\nWhich ending is best?", item["endings"], max_tokens=mt)
            pred = out["pred"]
            gold = choice_letter(int(item["answer"]))
            return _row(out, ok=pred == gold, pred=pred, gold=gold)
        stem = item["sentence"].replace("_", "_____")
        out = _ask_mc(client, stem, [item["option1"], item["option2"]], max_tokens=mt)
        pred = out["pred"]
        gold = "A" if str(item["answer"]) == "1" else "B"
        return _row(out, ok=pred == gold, pred=pred, gold=gold)

    run_pending(session, "knowledge", pending, work, rows)
    return rows


def run_math(
    client: ChatClient,
    limit: int | None,
    session: Session | None = None,
    budgets: dict[str, int] | None = None,
) -> list[dict]:
    mt = (budgets or DEFAULT_BUDGETS).get("math", DEFAULT_BUDGETS["math"])
    rows = []
    pending: list[tuple[str, Any]] = []
    for i, item in select_indexed_by_indices(read_jsonl("tiny_gsm8k.jsonl"), limit, MATH_CHALLENGE_INDICES):
        key = f"gsm:{i}"
        action = _take(session, "math", key, rows)
        if action == "stop":
            return rows
        if action == "skip":
            continue
        pending.append((key, item))

    def work(item: Any) -> dict[str, Any]:
        prompt = item["question"] + "\n\nEnd with #### <number> and nothing after."
        out = complete_for_item(client, prompt, max_tokens=mt)
        out["prompt"] = prompt
        parsed = parse_gsm_answer(out["text"] or "")
        pred = parsed["value"]
        out["parse_confidence"] = parsed["confidence"]
        out["parse_status"] = parsed["status"]
        out["raw_text"] = out["text"] or ""
        gold, _ = extract_gsm_number_conf(item["answer"])
        return _row(out, ok=pred == gold and pred is not None, pred=pred, gold=gold)

    run_pending(session, "math", pending, work, rows)
    return rows


def run_truth(
    client: ChatClient,
    limit: int | None,
    session: Session | None = None,
    budgets: dict[str, int] | None = None,
) -> list[dict]:
    mt = (budgets or DEFAULT_BUDGETS).get("truth", DEFAULT_BUDGETS["truth"])
    rows = []
    pending: list[tuple[str, Any]] = []
    for i, item in select_indexed_by_indices(read_jsonl("tiny_truthfulqa.jsonl"), limit, TRUTH_CHALLENGE_INDICES):
        key = f"tqa:{i}"
        action = _take(session, "truth", key, rows)
        if action == "stop":
            return rows
        if action == "skip":
            continue
        pending.append((key, item))

    def work(item: Any) -> dict[str, Any]:
        out = _ask_mc(client, item["question"], item["choices"], max_tokens=mt)
        pred = out["pred"]
        gold = choice_letter(int(item["answer"]))
        return _row(out, ok=pred == gold, pred=pred, gold=gold)

    run_pending(session, "truth", pending, work, rows)
    return rows


def run_instruct(
    client: ChatClient,
    limit: int | None,
    session: Session | None = None,
    budgets: dict[str, int] | None = None,
) -> list[dict]:
    mt = (budgets or DEFAULT_BUDGETS).get("instruct", DEFAULT_BUDGETS["instruct"])
    rows = []
    pending: list[tuple[str, Any]] = []
    for item in select_by_indices(read_jsonl("ifeval_100.jsonl"), limit, INSTRUCT_CHALLENGE_INDICES):
        key = f"ifeval:{item.get('key')}"
        action = _take(session, "instruct", key, rows)
        if action == "stop":
            return rows
        if action == "skip":
            continue
        pending.append((key, item))

    def work(item: Any) -> dict[str, Any]:
        out = complete_for_item(client, item["prompt"], max_tokens=mt)
        text = _strip_reasoning(out["text"] or "")
        out = dict(out)
        out["text"] = text
        ok = item_ok(item, text)
        out["parse_confidence"] = "not_applicable"
        return _row(
            out,
            ok=ok,
            pred=text[:120],
            prompt=item.get("prompt") or "",
            instruction_id_list=copy.deepcopy(item.get("instruction_id_list") or []),
            kwargs=copy.deepcopy(item.get("kwargs") or []),
            grader={"name": "ifeval-local", "item_key": item.get("key")},
        )

    run_pending(session, "instruct", pending, work, rows)
    return rows


def build_overall_flags(stats: dict[str, dict[str, Any]]) -> list[str]:
    """Name every category whose topline is unreliable instead of hiding it."""
    flags: list[str] = []
    for category in CATEGORIES:
        category_stats = stats.get(category) or {}
        if category_stats.get("truncated"):
            flags.append(f"truncated:{category}")
        if category_stats.get("trunc_in_think"):
            flags.append(f"trunc-in-think:{category}")
    for category in CATEGORIES:
        category_stats = stats.get(category) or {}
        if category_stats.get("loop_failures"):
            flags.append(f"loop-failures:{category}")
    for category in CATEGORIES:
        category_stats = stats.get(category) or {}
        _, _, _, missing = _confidence_counts(category_stats, category_stats.get("n") or 0)
        if missing:
            flags.append(f"missing-parse-confidence:{category}")
    for category in CATEGORIES:
        category_stats = stats.get(category) or {}
        high, low, _, _ = _confidence_counts(category_stats, category_stats.get("n") or 0)
        applicable = high + low
        # not_applicable and missing rows are deliberately excluded: this gate asks how
        # often an actually-used parser fell through to its low-confidence fallback.
        if applicable and low / applicable > 0.2:
            flags.append(f"low-confidence-parses:{category}")
    return flags


def _confidence_counts(category_stats: dict[str, Any], n: int) -> tuple[int, int, int, int]:
    """Return high/low/not-applicable/missing counts, inferring only the missing bucket
    for pre-accounting artifacts. Unaccounted rows must never be presented as high confidence.
    """
    high = category_stats.get("parse_high_confidence") or 0
    low = category_stats.get("parse_low_confidence") or 0
    not_applicable = category_stats.get("parse_confidence_not_applicable") or 0
    missing = category_stats.get("parse_confidence_missing")
    if missing is None:
        missing = max(n - high - low - not_applicable, 0)
    return high, low, not_applicable, missing


def run_battery(
    client: ChatClient,
    limit: int | None = None,
    session: Session | None = None,
    *,
    skip_code_exec: bool = False,
    configured_ctx: int | None = None,
) -> dict:
    resolved_budgets = dict(client.policy.budgets)
    with deadline_scope(session.budget.deadline if session is not None else None):
        server_props = getattr(client, "server_props", None)
        if server_props is None:
            server_props = fetch_server_props(client.base_url, client.api_key)
        policy_probe_details = probe_policy(client)
    probe_failed = policy_probe_details.get("status") != "ok"
    if probe_failed:
        if session is None:
            raise RuntimeError(f"policy probe failed: {policy_probe_details.get('reason', 'unknown failure')}")
        session.stopped = session.budget.expired()
        session.errors.append({"phase": "preflight", "status": "deadline" if session.stopped else "error"})
        print("PREFLIGHT FAILED: no scored requests will be sent", flush=True)
    output_reserve = max(resolved_budgets.values()) if resolved_budgets else 1024
    preflight = assemble_preflight(
        requested_model=client.model,
        server_props=server_props,
        probe=policy_probe_details,
        n_items=expected_scored_items(limit, skip_code_exec=skip_code_exec),
        output_reserve=output_reserve,
        configured_ctx=configured_ctx,
        thinking=bool(client.policy.thinking),
        cache_key=f"{client.base_url}|{client.model}|chat",
        store_cache=True,
    )
    if session is not None:
        session.collecting = True
    packs = {
        "knowledge": run_knowledge(client, limit, session, resolved_budgets),
        "math": run_math(client, limit, session, resolved_budgets),
        "truth": run_truth(client, limit, session, resolved_budgets),
        "instruct": run_instruct(client, limit, session, resolved_budgets),
        "code": run_code(
            client,
            limit,
            session,
            resolved_budgets.get("code"),
            skip_code_exec=skip_code_exec,
        ),
        "tools": run_tools(client, limit, session, resolved_budgets.get("tools")),
    }
    diagnostics = None
    segment = None
    if session is not None:
        session.collecting = False
        if not probe_failed:
            execute_tasks(balanced_order(session.pending_tasks), session)
        latest = {
            cat: [row for category, key in session.plan_keys if category == cat
                  if (row := session.journal.get(cat, key)) is not None]
            for cat in CATEGORIES
        }
        for cat in CATEGORIES:
            keys = [key for category, key in session.plan_keys if category == cat]
            first = [session.journal.first(cat, key) for key in keys]
            packs[cat] = [row for row in first if row is not None]
        if session.retry_mode in {"failed", "incomplete"} or any(
            len(session.journal.attempts_for(cat, key)) > 1 for cat, key in session.plan_keys
        ):
            latest_scores = {cat: category_score(rows) for cat, rows in latest.items()}
            diagnostics = {"label": "latest-attempt diagnostic; NOT pass@1",
                           "attempt_policy": "latest-attempt-diagnostic",
                           "latest_items": latest, "categories": latest_scores,
                           "overall": overall_score(latest_scores) if any(v is not None for v in latest_scores.values()) else None}
        segment = segment_receipt(session, session.segment_attempts)
        session.journal.append_event({"_sixcat_segment": segment})
    cats = {k: category_score(v) for k, v in packs.items()}
    stats = {k: category_stats(v) for k, v in packs.items()}
    timed_out = bool(session and session.stopped)
    overall_flags = build_overall_flags(stats)
    code_execution = "disabled" if skip_code_exec else "host-guarded"
    if skip_code_exec:
        overall_flags.append("code-exec-disabled")
    overall_value = overall_score(cats) if any(v is not None for v in cats.values()) else None
    manifest = benchmark_manifest(limit, skip_code_exec)
    result = {
        "model": client.model,
        "artifact_id": getattr(client, "artifact_id", None),
        "server_identity": getattr(client, "server_identity", None),
        "attempt_policy": ATTEMPT_POLICY,
        "schedule": SCHEDULE if session is not None else "category-order",
        "concurrency": session.concurrency if session is not None else 1,
        "benchmark_manifest": manifest,
        "benchmark_fingerprint": manifest["fingerprint"],
        "expected_n": expected_counts(limit, skip_code_exec),
        "diagnostics": diagnostics,
        "execution": segment,
        "errors": copy.deepcopy(session.errors) if session is not None else [],
        "base_url": client.base_url,
        "request_timeout_seconds": getattr(client, "timeout", None),
        "server_props": server_props,
        "preflight": preflight,
        "policy": client.policy.to_dict(),
        "policy_source": client.policy.source,
        "policy_probe": policy_probe_details["status"],
        "policy_probe_details": policy_probe_details,
        "policy_fingerprint": client.policy.fingerprint,
        "budgets": resolved_budgets,
        "parser": PARSER_VERSION,
        "code_execution": code_execution,
        "result_schema": RESULT_SCHEMA,
        "transport": getattr(client, "transport", "openai"),
        "limit": limit,
        "limit_scope": "per_category",
        "selection_profile": SELECTION_PROFILE,
        "selection_fingerprint": SELECTION_FINGERPRINT,
        "timed_out": timed_out,
        "categories": cats,
        "stats": stats,
        "overall": {"policy": client.policy.name, "score": overall_value},
        "overall_label": f"overall[{client.policy.name}]",
        "overall_flags": overall_flags,
        "n": {k: len(v) for k, v in packs.items()},
        "items": packs,
        "speed": suite_speed(packs),
    }
    result["complete"] = result["n"] == result["expected_n"] and not timed_out and not probe_failed
    result["speed"]["coverage"] = f"{result['speed']['items']}/{sum(result['n'].values())}"
    if not result["complete"]:
        result["overall_flags"].append("incomplete-scope")
    if session is not None:
        result["execution_segments"] = [event["_sixcat_segment"] for event in session.journal.events if "_sixcat_segment" in event]
    offer = continuation_offer(result)
    if session is not None and (session.retry_mode or session.retry_keys or session.rescored):
        offer.update(session.continuation_receipt())
    result["continuation"] = offer
    return result


def render_table(result: dict) -> str:
    policy = result.get("policy") or {}
    policy_name = policy.get("name")
    if not policy_name:
        raise ValueError("cannot render a bare overall without a policy label")
    header = (
        f"{'category':<12} {'score':>8} {'n':>5} {'trunc':>6} {'loops':>6} "
        f"{'high':>5} {'low':>5} {'n/a':>5} {'miss':>5} {'pp':>7} {'tg':>7} {'tps':>7}"
    )
    separator = "-" * len(header)
    lines = [
        f"model: {result.get('model')}",
        f"url:   {result.get('base_url')}",
        f"policy: {policy_name} ({result.get('policy_fingerprint')})",
        f"source: {result.get('policy_source')}",
        f"code execution: {result.get('code_execution', 'unrecorded')}",
        f"attempts: {result.get('attempt_policy', 'legacy/unrecorded')}",
        f"concurrency: {result.get('concurrency', 1)}; schedule: {result.get('schedule', 'legacy/unrecorded')}",
    ]
    preflight = result.get("preflight")
    if isinstance(preflight, dict):
        lines.extend(["", format_preflight(preflight)])
    lines.extend(
        [
            "",
            header,
            separator,
        ]
    )
    stats = result.get("stats") or {}
    any_truncated = False
    missing_categories: list[str] = []
    for k in CATEGORIES:
        sc = result["categories"].get(k)
        n = result["n"].get(k, 0)
        category_stats = stats.get(k) or {}
        trunc = category_stats.get("truncated", 0) or 0
        loops = category_stats.get("loop_failures", 0) or 0
        high, low, not_applicable, missing = _confidence_counts(category_stats, n)
        if trunc:
            any_truncated = True
        if missing:
            missing_categories.append(f"{k}={missing}/{n}")
        cell = "  n/a" if sc is None else f"{sc:7.1f}"
        trunc_cell = f"{trunc:6d}" if trunc else "     0"
        loop_cell = f"{loops:6d}" if loops else "     0"
        prefill = category_stats.get("prefill_tps_p50")
        decode = category_stats.get("decode_tps_p50")
        tps = category_stats.get("tps_mean")
        pp_cell = f"{prefill:7.1f}" if isinstance(prefill, (int, float)) and not isinstance(prefill, bool) else "    n/a"
        tg_cell = f"{decode:7.1f}" if isinstance(decode, (int, float)) and not isinstance(decode, bool) else "    n/a"
        tps_cell = f"{tps:7.1f}" if isinstance(tps, (int, float)) and not isinstance(tps, bool) else "    n/a"
        lines.append(
            f"{k:<12} {cell} {n:5d} {trunc_cell} {loop_cell} "
            f"{high:5d} {low:5d} {not_applicable:5d} {missing:5d} {pp_cell} {tg_cell} {tps_cell}"
        )
    lines.append(separator)
    overall = result.get("overall") or {}
    if overall.get("policy") != policy_name:
        raise ValueError("overall policy label does not match resolved policy")
    ov = overall.get("score")
    ov_flags = result.get("overall_flags") or []
    ov_suffix = f"  [{', '.join(ov_flags)}]" if ov_flags else ""
    overall_label = f"overall[{policy_name}]"
    lines.append(f"{overall_label:<18} {ov:7.1f}{ov_suffix}" if ov is not None else f"{overall_label:<18} n/a")
    speed = result.get("speed") or {}
    suite_tps = speed.get("suite_tps")
    tps_mean = speed.get("tps_mean")
    if isinstance(suite_tps, (int, float)) or isinstance(tps_mean, (int, float)):
        total_ctok = speed.get("total_ctok")
        total_wall = speed.get("total_wall_s")
        ctok_cell = f"{total_ctok:.0f}" if isinstance(total_ctok, (int, float)) else "n/a"
        wall_cell = f"{total_wall:.1f}s" if isinstance(total_wall, (int, float)) else "n/a"
        suite_cell = f"{suite_tps:.1f}" if isinstance(suite_tps, (int, float)) else "n/a"
        mean_cell = f"{tps_mean:.1f}" if isinstance(tps_mean, (int, float)) else "n/a"
        lines.append(f"speed: {ctok_cell} ctok / {wall_cell}  suite_tps {suite_cell}  mean {mean_cell}")
    tok_header = f"{'tokens':<12} {'rtok':>8} {'atok':>8} {'empty':>6} {'think':>6}"
    lines.extend(["", tok_header, "-" * len(tok_header)])
    total_rtok = 0
    total_atok = 0
    saw_rtok = False
    saw_atok = False
    any_think_trunc = False
    for k in CATEGORIES:
        category_stats = stats.get(k) or {}
        rtok = category_stats.get("rtok_sum")
        atok = category_stats.get("atok_sum")
        empty = category_stats.get("empty_answer") or 0
        think_trunc = category_stats.get("trunc_in_think") or 0
        if think_trunc:
            any_think_trunc = True
        if isinstance(rtok, int):
            total_rtok += rtok
            saw_rtok = True
            rtok_cell = f"{rtok:8d}"
        else:
            rtok_cell = "     n/a"
        if isinstance(atok, int):
            total_atok += atok
            saw_atok = True
            atok_cell = f"{atok:8d}"
        else:
            atok_cell = "     n/a"
        lines.append(f"{k:<12} {rtok_cell} {atok_cell} {empty:6d} {think_trunc:6d}")
    rtok_tot = f"{total_rtok}" if saw_rtok else "n/a"
    atok_tot = f"{total_atok}" if saw_atok else "n/a"
    lines.append(f"tokens: rtok={rtok_tot} atok={atok_tot}  (API split; n/a if engine omitted reasoning_tokens)")
    if any_think_trunc:
        lines.append(
            "WARNING: trunc_in_think>0 — answer channel empty at max_tokens; overall is not comparable to an untruncated run"
        )
    if result.get("timed_out"):
        lines.append("stopped: time limit")
    continuation = result.get("continuation") or {}
    if continuation.get("remaining") or continuation.get("failed"):
        lines.append(
            "continuation: "
            f"remaining={continuation.get('remaining', 0)} "
            f"failed={continuation.get('failed', 0)} "
            "merge with --retry remaining|failed|incomplete on the same --log/--out"
        )
    if any_truncated:
        lines.append(
            "WARNING: at least one category has truncated completions (finish_reason=length) — "
            "affected scores are not reliable, see --budget"
        )
    if missing_categories:
        lines.append(
            "WARNING: missing parse confidence for "
            + ", ".join(missing_categories)
            + " — affected rows are not self-auditing"
        )
    execution = result.get("execution") or {}
    if execution:
        throughput = execution.get("throughput_tps")
        lines.append(f"session: {execution['elapsed_s']:.2f}s; responses={execution['responses']}; "
                     f"aggregate_tps={throughput:.2f}" if throughput is not None else "session throughput: n/a")
        lines.append(f"timing coverage: {execution.get('throughput_coverage')}; concurrency={execution['concurrency']}")
    if result.get("complete") is False:
        lines.append("PARTIAL / PROVISIONAL: scope unfinished; do not treat this as a complete SixCat score.")
    diagnostics = result.get("diagnostics")
    if diagnostics:
        lines.append(f"diagnostic latest-attempt overall: {diagnostics.get('overall')} (NOT pass@1; headline unchanged)")
    return "\n".join(lines)
