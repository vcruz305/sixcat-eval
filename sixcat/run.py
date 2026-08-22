from __future__ import annotations

import copy
from typing import Any

from .client import ChatClient, fetch_server_props
from .code import run_code
from .dataio import read_jsonl, take
from .instruct import item_ok
from .journal import Session, emit, gate
from .policy import STRICT_BUDGETS, probe_policy
from .report import PARSER_VERSION, RESULT_SCHEMA
from .score import (
    CATEGORIES,
    category_score,
    category_stats,
    extract_gsm_number_conf,
    extract_mc_letter_conf,
    is_loop_failure,
    overall_score,
    suite_speed,
)
from .tools import run_tools

# Phase 3 (sixcat v2.1, B3): right-sized from Phase 1's own measured truncation, not
# guessed. At the old defaults (knowledge/truth=32, math=256, instruct=400, code=512,
# tools=128) a live 20-item run showed knowledge truncating 11/80 (~14%) and instruct
# 8/20 (40%) -- both silently scored as wrong answers, not as incomplete. These are the
# "no-think" values; Phase 4 adds a thinking-mode column once the policy layer can toggle
# reasoning on and these need real headroom for a trace (measured up to 553 tokens on math
# alone -- see sixcat-sampling-policy-review-2026-08-20.md).
DEFAULT_BUDGETS = STRICT_BUDGETS

LETTERS = "ABCDEFGHIJKLMNOP"


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


def _gate(session: Session | None, cat: str, key: str):
    return gate(session, cat, key)


def _emit(session: Session | None, cat: str, key: str, row: dict[str, Any]) -> dict[str, Any]:
    return emit(session, cat, key, row)


def _row(out: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Phase 1 (sixcat v2.1): every emitted row carries finish/ctok/request_params so
    truncation and budget questions are answerable from the JSONL after the fact.
    """
    usage = out.get("usage") or {}
    row: dict[str, Any] = dict(extra)
    row["finish"] = out.get("finish")
    row["ctok"] = usage.get("completion_tokens")
    row["ptok"] = usage.get("prompt_tokens")
    row["request_params"] = out.get("request_params")
    if "parse_confidence" in out:
        row["parse_confidence"] = out["parse_confidence"]
    if "raw_text" in out:
        row["raw_text"] = out["raw_text"]
    elif "text" in out:
        row["raw_text"] = out["text"] or ""
    if "reasoning_content" in out:
        row["reasoning_content"] = out["reasoning_content"]
    for key in (
        "prefill_tps",
        "decode_tps",
        "prefill_ms",
        "decode_ms",
        "prefill_n",
        "decode_n",
        "speed_source",
        "wall_s",
        "wall_tps",
    ):
        if key in out:
            row[key] = out[key]
    if row.get("wall_tps") is None:
        ctok = row.get("ctok")
        wall = row.get("wall_s")
        if (
            isinstance(ctok, (int, float))
            and not isinstance(ctok, bool)
            and isinstance(wall, (int, float))
            and not isinstance(wall, bool)
            and wall > 0
        ):
            row["wall_tps"] = float(ctok) / float(wall)
    row["loop"] = is_loop_failure(row)
    return row


def _ask_mc(client: ChatClient, stem: str, choices: list[str], max_tokens: int = 32) -> dict[str, Any]:
    lines = [stem, ""]
    for i, c in enumerate(choices):
        lines.append(f"{choice_letter(i)}. {c}")
    lines.append("")
    lines.append("Reply with only the letter of the correct option.")
    out = client.complete("\n".join(lines), max_tokens=max_tokens)
    letter, conf = extract_mc_letter_conf(out["text"] or "")
    out["pred"] = letter or ""
    out["parse_confidence"] = conf
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
    for i, item in enumerate(take(read_jsonl("tiny_mmlu.jsonl"), limit)):
        key = f"mmlu:{i}"
        g = _gate(session, "knowledge", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        out = _ask_mc(client, item["question"], item["choices"], max_tokens=mt)
        pred = out["pred"]
        gold = choice_letter(int(item["answer"]))
        rows.append(_emit(session, "knowledge", key, _row(out, ok=pred == gold, pred=pred, gold=gold)))
    for i, item in enumerate(take(read_jsonl("tiny_arc.jsonl"), limit)):
        key = f"arc:{i}"
        g = _gate(session, "knowledge", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        out = _ask_mc(client, item["question"], item["texts"], max_tokens=mt)
        pred = out["pred"]
        gold = arc_answer_letter(item)
        rows.append(_emit(session, "knowledge", key, _row(out, ok=pred == gold, pred=pred, gold=gold)))
    for i, item in enumerate(take(read_jsonl("tiny_hellaswag.jsonl"), limit)):
        key = f"hellaswag:{i}"
        g = _gate(session, "knowledge", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        out = _ask_mc(client, item["ctx"] + "\n\nWhich ending is best?", item["endings"], max_tokens=mt)
        pred = out["pred"]
        gold = choice_letter(int(item["answer"]))
        rows.append(_emit(session, "knowledge", key, _row(out, ok=pred == gold, pred=pred, gold=gold)))
    for i, item in enumerate(take(read_jsonl("tiny_winogrande.jsonl"), limit)):
        key = f"winogrande:{i}"
        g = _gate(session, "knowledge", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        stem = item["sentence"].replace("_", "_____")
        out = _ask_mc(client, stem, [item["option1"], item["option2"]], max_tokens=mt)
        pred = out["pred"]
        gold = "A" if str(item["answer"]) == "1" else "B"
        rows.append(_emit(session, "knowledge", key, _row(out, ok=pred == gold, pred=pred, gold=gold)))
    return rows


def run_math(
    client: ChatClient,
    limit: int | None,
    session: Session | None = None,
    budgets: dict[str, int] | None = None,
) -> list[dict]:
    mt = (budgets or DEFAULT_BUDGETS).get("math", DEFAULT_BUDGETS["math"])
    rows = []
    for i, item in enumerate(take(read_jsonl("tiny_gsm8k.jsonl"), limit)):
        key = f"gsm:{i}"
        g = _gate(session, "math", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        out = client.complete(
            item["question"] + "\n\nEnd with #### <number> and nothing after.",
            max_tokens=mt,
        )
        pred, conf = extract_gsm_number_conf(out["text"] or "")
        out["parse_confidence"] = conf
        out["raw_text"] = out["text"] or ""
        gold, _ = extract_gsm_number_conf(item["answer"])
        rows.append(
            _emit(
                session,
                "math",
                key,
                _row(out, ok=pred == gold and pred is not None, pred=pred, gold=gold),
            )
        )
    return rows


def run_truth(
    client: ChatClient,
    limit: int | None,
    session: Session | None = None,
    budgets: dict[str, int] | None = None,
) -> list[dict]:
    mt = (budgets or DEFAULT_BUDGETS).get("truth", DEFAULT_BUDGETS["truth"])
    rows = []
    for i, item in enumerate(take(read_jsonl("tiny_truthfulqa.jsonl"), limit)):
        key = f"tqa:{i}"
        g = _gate(session, "truth", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        out = _ask_mc(client, item["question"], item["choices"], max_tokens=mt)
        pred = out["pred"]
        gold = choice_letter(int(item["answer"]))
        rows.append(_emit(session, "truth", key, _row(out, ok=pred == gold, pred=pred, gold=gold)))
    return rows


def run_instruct(
    client: ChatClient,
    limit: int | None,
    session: Session | None = None,
    budgets: dict[str, int] | None = None,
) -> list[dict]:
    mt = (budgets or DEFAULT_BUDGETS).get("instruct", DEFAULT_BUDGETS["instruct"])
    rows = []
    for item in take(read_jsonl("ifeval_100.jsonl"), limit):
        key = f"ifeval:{item.get('key')}"
        g = _gate(session, "instruct", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        out = client.complete(item["prompt"], max_tokens=mt)
        text = out["text"] or ""
        ok = item_ok(item, text)
        out["parse_confidence"] = "not_applicable"
        rows.append(
            _emit(
                session,
                "instruct",
                key,
                _row(
                    out,
                    ok=ok,
                    pred=text[:120],
                    prompt=item.get("prompt") or "",
                    instruction_id_list=copy.deepcopy(item.get("instruction_id_list") or []),
                    kwargs=copy.deepcopy(item.get("kwargs") or []),
                    grader={"name": "ifeval-local", "item_key": item.get("key")},
                ),
            )
        )
    return rows


def build_overall_flags(stats: dict[str, dict[str, Any]]) -> list[str]:
    """Name every category whose topline is unreliable instead of hiding it."""
    flags: list[str] = []
    for category in CATEGORIES:
        category_stats = stats.get(category) or {}
        if category_stats.get("truncated"):
            flags.append(f"truncated:{category}")
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
) -> dict:
    resolved_budgets = dict(client.policy.budgets)
    server_props = fetch_server_props(client.base_url, client.api_key)
    policy_probe_details = probe_policy(client)
    if policy_probe_details.get("status") != "ok":
        raise RuntimeError(f"policy probe failed: {policy_probe_details.get('reason', 'unknown failure')}")
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
    cats = {k: category_score(v) for k, v in packs.items()}
    stats = {k: category_stats(v) for k, v in packs.items()}
    timed_out = bool(session and session.stopped)
    overall_flags = build_overall_flags(stats)
    code_execution = "disabled" if skip_code_exec else "host-guarded"
    if skip_code_exec:
        overall_flags.append("code-exec-disabled")
    overall_value = overall_score(cats) if any(v is not None for v in cats.values()) else None
    return {
        "model": client.model,
        "base_url": client.base_url,
        "request_timeout_seconds": getattr(client, "timeout", None),
        "server_props": server_props,
        "policy": client.policy.to_dict(),
        "policy_source": client.policy.source,
        "policy_probe": policy_probe_details["status"],
        "policy_probe_details": policy_probe_details,
        "policy_fingerprint": client.policy.fingerprint,
        "budgets": resolved_budgets,
        "parser": PARSER_VERSION,
        "code_execution": code_execution,
        "result_schema": RESULT_SCHEMA,
        "limit": limit,
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
        "",
        header,
        separator,
    ]
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
    if result.get("timed_out"):
        lines.append("stopped: time limit")
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
    return "\n".join(lines)
