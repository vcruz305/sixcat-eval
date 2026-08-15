from __future__ import annotations

from typing import Any

from .client import ChatClient
from .code import run_code
from .dataio import read_jsonl, take
from .instruct import item_ok
from .journal import Session, emit, gate
from .score import CATEGORIES, category_score, extract_gsm_number, extract_mc_letter, overall_score
from .tools import run_tools

LETTERS = "ABCDEFGHIJKLMNOP"


def choice_letter(i: int) -> str:
    if i < 0 or i >= len(LETTERS):
        raise IndexError(i)
    return LETTERS[i]


def _gate(session: Session | None, cat: str, key: str):
    return gate(session, cat, key)


def _emit(session: Session | None, cat: str, key: str, row: dict[str, Any]) -> dict[str, Any]:
    return emit(session, cat, key, row)


def _ask_mc(client: ChatClient, stem: str, choices: list[str], max_tokens: int = 32) -> str:
    lines = [stem, ""]
    for i, c in enumerate(choices):
        lines.append(f"{choice_letter(i)}. {c}")
    lines.append("")
    lines.append("Reply with only the letter of the correct option.")
    out = client.complete("\n".join(lines), max_tokens=max_tokens)
    return extract_mc_letter(out["text"] or "") or ""


def run_knowledge(client: ChatClient, limit: int | None, session: Session | None = None) -> list[dict]:
    rows: list[dict] = []
    for i, item in enumerate(take(read_jsonl("tiny_mmlu.jsonl"), limit)):
        key = f"mmlu:{i}"
        g = _gate(session, "knowledge", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        pred = _ask_mc(client, item["question"], item["choices"])
        gold = choice_letter(int(item["answer"]))
        rows.append(_emit(session, "knowledge", key, {"ok": pred == gold, "pred": pred, "gold": gold}))
    for i, item in enumerate(take(read_jsonl("tiny_arc.jsonl"), limit)):
        key = f"arc:{i}"
        g = _gate(session, "knowledge", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        pred = _ask_mc(client, item["question"], item["texts"])
        gold = str(item["answer"]).upper()
        rows.append(_emit(session, "knowledge", key, {"ok": pred == gold, "pred": pred, "gold": gold}))
    for i, item in enumerate(take(read_jsonl("tiny_hellaswag.jsonl"), limit)):
        key = f"hellaswag:{i}"
        g = _gate(session, "knowledge", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        pred = _ask_mc(client, item["ctx"] + "\n\nWhich ending is best?", item["endings"])
        gold = choice_letter(int(item["answer"]))
        rows.append(_emit(session, "knowledge", key, {"ok": pred == gold, "pred": pred, "gold": gold}))
    for i, item in enumerate(take(read_jsonl("tiny_winogrande.jsonl"), limit)):
        key = f"winogrande:{i}"
        g = _gate(session, "knowledge", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        stem = item["sentence"].replace("_", "_____")
        pred = _ask_mc(client, stem, [item["option1"], item["option2"]])
        gold = "A" if str(item["answer"]) == "1" else "B"
        rows.append(_emit(session, "knowledge", key, {"ok": pred == gold, "pred": pred, "gold": gold}))
    return rows


def run_math(client: ChatClient, limit: int | None, session: Session | None = None) -> list[dict]:
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
            max_tokens=256,
        )
        pred = extract_gsm_number(out["text"] or "")
        gold = extract_gsm_number(item["answer"])
        rows.append(_emit(session, "math", key, {"ok": pred == gold and pred is not None, "pred": pred, "gold": gold}))
    return rows


def run_truth(client: ChatClient, limit: int | None, session: Session | None = None) -> list[dict]:
    rows = []
    for i, item in enumerate(take(read_jsonl("tiny_truthfulqa.jsonl"), limit)):
        key = f"tqa:{i}"
        g = _gate(session, "truth", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        pred = _ask_mc(client, item["question"], item["choices"])
        gold = choice_letter(int(item["answer"]))
        rows.append(_emit(session, "truth", key, {"ok": pred == gold, "pred": pred, "gold": gold}))
    return rows


def run_instruct(client: ChatClient, limit: int | None, session: Session | None = None) -> list[dict]:
    rows = []
    for item in take(read_jsonl("ifeval_100.jsonl"), limit):
        key = f"ifeval:{item.get('key')}"
        g = _gate(session, "instruct", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        out = client.complete(item["prompt"], max_tokens=400)
        text = out["text"] or ""
        ok = item_ok(item, text)
        rows.append(_emit(session, "instruct", key, {"ok": ok, "pred": text[:120]}))
    return rows


def run_battery(client: ChatClient, limit: int | None = None, session: Session | None = None) -> dict:
    packs = {
        "knowledge": run_knowledge(client, limit, session),
        "math": run_math(client, limit, session),
        "truth": run_truth(client, limit, session),
        "instruct": run_instruct(client, limit, session),
        "code": run_code(client, limit, session),
        "tools": run_tools(client, limit, session),
    }
    cats = {k: category_score(v) for k, v in packs.items()}
    timed_out = bool(session and session.stopped)
    return {
        "model": client.model,
        "base_url": client.base_url,
        "limit": limit,
        "timed_out": timed_out,
        "categories": cats,
        "overall": overall_score(cats) if any(v is not None for v in cats.values()) else None,
        "n": {k: len(v) for k, v in packs.items()},
        "items": packs,
    }


def render_table(result: dict) -> str:
    lines = [
        f"model: {result.get('model')}",
        f"url:   {result.get('base_url')}",
        "",
        f"{'category':<12} {'score':>8} {'n':>5}",
        "-" * 28,
    ]
    for k in CATEGORIES:
        sc = result["categories"].get(k)
        n = result["n"].get(k, 0)
        cell = "  n/a" if sc is None else f"{sc:7.1f}"
        lines.append(f"{k:<12} {cell} {n:5d}")
    lines.append("-" * 28)
    ov = result.get("overall")
    lines.append(f"{'overall':<12} {ov:7.1f}" if ov is not None else "overall        n/a")
    if result.get("timed_out"):
        lines.append("stopped: time limit")
    return "\n".join(lines)
