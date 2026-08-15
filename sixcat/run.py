from __future__ import annotations

from .client import ChatClient
from .code import run_code
from .dataio import read_jsonl, take
from .instruct import item_ok
from .score import CATEGORIES, category_score, extract_gsm_number, extract_mc_letter, overall_score
from .tools import run_tools

LETTERS = "ABCD"


def _ask_mc(client: ChatClient, stem: str, choices: list[str], max_tokens: int = 32) -> str:
    lines = [stem, ""]
    for i, c in enumerate(choices):
        lines.append(f"{LETTERS[i]}. {c}")
    lines.append("")
    lines.append("Reply with only the letter of the correct option.")
    out = client.complete("\n".join(lines), max_tokens=max_tokens)
    return extract_mc_letter(out["text"] or "") or ""


def run_knowledge(client: ChatClient, limit: int | None) -> list[dict]:
    rows: list[dict] = []
    for item in take(read_jsonl("tiny_mmlu.jsonl"), limit):
        pred = _ask_mc(client, item["question"], item["choices"])
        gold = LETTERS[int(item["answer"])]
        rows.append({"id": "mmlu", "ok": pred == gold, "pred": pred, "gold": gold})
    for item in take(read_jsonl("tiny_arc.jsonl"), limit):
        pred = _ask_mc(client, item["question"], item["texts"])
        gold = str(item["answer"]).upper()
        rows.append({"id": "arc", "ok": pred == gold, "pred": pred, "gold": gold})
    for item in take(read_jsonl("tiny_hellaswag.jsonl"), limit):
        pred = _ask_mc(client, item["ctx"] + "\n\nWhich ending is best?", item["endings"])
        gold = LETTERS[int(item["answer"])]
        rows.append({"id": "hellaswag", "ok": pred == gold, "pred": pred, "gold": gold})
    for item in take(read_jsonl("tiny_winogrande.jsonl"), limit):
        stem = item["sentence"].replace("_", "_____")
        pred = _ask_mc(client, stem, [item["option1"], item["option2"]])
        gold = "A" if str(item["answer"]) == "1" else "B"
        rows.append({"id": "winogrande", "ok": pred == gold, "pred": pred, "gold": gold})
    return rows


def run_math(client: ChatClient, limit: int | None) -> list[dict]:
    rows = []
    for i, item in enumerate(take(read_jsonl("tiny_gsm8k.jsonl"), limit)):
        out = client.complete(
            item["question"] + "\n\nEnd with #### <number> and nothing after.",
            max_tokens=256,
        )
        pred = extract_gsm_number(out["text"] or "")
        gold = extract_gsm_number(item["answer"])
        rows.append({"id": f"gsm{i}", "ok": pred == gold and pred is not None, "pred": pred, "gold": gold})
    return rows


def run_truth(client: ChatClient, limit: int | None) -> list[dict]:
    rows = []
    for i, item in enumerate(take(read_jsonl("tiny_truthfulqa.jsonl"), limit)):
        pred = _ask_mc(client, item["question"], item["choices"])
        gold = LETTERS[int(item["answer"])]
        rows.append({"id": f"tqa{i}", "ok": pred == gold, "pred": pred, "gold": gold})
    return rows


def run_instruct(client: ChatClient, limit: int | None) -> list[dict]:
    rows = []
    for item in take(read_jsonl("ifeval_100.jsonl"), limit):
        out = client.complete(item["prompt"], max_tokens=400)
        text = out["text"] or ""
        ok = item_ok(item, text)
        rows.append({"id": item.get("key"), "ok": ok, "pred": text[:120]})
    return rows


def run_battery(client: ChatClient, limit: int | None = None) -> dict:
    packs = {
        "knowledge": run_knowledge(client, limit),
        "math": run_math(client, limit),
        "truth": run_truth(client, limit),
        "instruct": run_instruct(client, limit),
        "code": run_code(client, limit),
        "tools": run_tools(client, limit),
    }
    cats = {k: category_score(v) for k, v in packs.items()}
    return {
        "model": client.model,
        "base_url": client.base_url,
        "limit": limit,
        "categories": cats,
        "overall": overall_score(cats),
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
    return "\n".join(lines)
