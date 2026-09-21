"""Offline regrading and optional EvalPlus export. Never generates new answers."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from .dataio import read_jsonl
from .manifest import ATTEMPT_POLICY, benchmark_manifest
from .report import PARSER_VERSION, load_result, normalise_result
from .score import (CATEGORIES, _strip_reasoning, category_score, category_stats,
                    extract_gsm_number_conf, extract_mc_letter_conf, overall_score, suite_speed)
from .storage import atomic_write_json, atomic_write_text


def catalog() -> dict:
    result = {}
    for name, filename in (("mmlu", "tiny_mmlu.jsonl"), ("arc", "tiny_arc.jsonl"),
                           ("hellaswag", "tiny_hellaswag.jsonl"), ("winogrande", "tiny_winogrande.jsonl")):
        for i, item in enumerate(read_jsonl(filename)):
            result[("knowledge", f"{name}:{i}")] = (name, item)
    for cat, prefix, filename in (("math", "gsm", "tiny_gsm8k.jsonl"), ("truth", "tqa", "tiny_truthfulqa.jsonl")):
        for i, item in enumerate(read_jsonl(filename)):
            result[(cat, f"{prefix}:{i}")] = (cat, item)
    for item in read_jsonl("ifeval_100.jsonl"):
        result[("instruct", f"ifeval:{item['key']}")] = ("instruct", item)
    for item in read_jsonl("humaneval.jsonl"):
        result[("code", item["task_id"])] = ("code", item)
    from .tools import ITEMS
    for name, expected, prompt in ITEMS:
        result[("tools", f"tool:{name}")] = ("tools", (expected, prompt))
    return result


def regrade(document: dict) -> dict:
    from .code import _run_humaneval
    from .instruct import item_ok
    from .run import arc_answer_letter, build_overall_flags, continuation_offer
    from .tools import _tool_answer_ok
    if document.get("attempt_policy") != ATTEMPT_POLICY:
        raise ValueError("offline rescore requires known first-response provenance; legacy latest-attempt artifacts cannot be upgraded silently")
    manifest = benchmark_manifest(document.get("limit"), document.get("code_execution") == "disabled")
    old_manifest = document.get("benchmark_manifest") or {}
    for field in ("data_sha256", "tools_sha256", "selected_keys"):
        if old_manifest.get(field) != manifest[field]:
            raise ValueError(f"cannot regrade: source {field} differs from the installed benchmark")
    result = copy.deepcopy(document)
    tasks = catalog()
    for cat in CATEGORIES:
        for row in result["items"][cat]:
            key = str(row.get("key") or row.get("id"))
            kind, item = tasks[(cat, key)]
            text = _strip_reasoning(str(row.get("source_text", row.get("raw_text")) or ""))
            row["previous_verdict"] = {"ok": row["ok"], "parser": document["parser"]}
            row["raw_text"] = text
            if cat in {"knowledge", "truth"}:
                if kind == "mmlu" or cat == "truth":
                    n, gold = len(item["choices"]), chr(65 + int(item["answer"]))
                elif kind == "arc":
                    n, gold = len(item["texts"]), arc_answer_letter(item)
                elif kind == "hellaswag":
                    n, gold = len(item["endings"]), chr(65 + int(item["answer"]))
                else:
                    n, gold = 2, "A" if str(item["answer"]) == "1" else "B"
                pred, conf = extract_mc_letter_conf(text, valid_letters="ABCDEFGHIJKLMNOP"[:n])
                row.update(pred=pred or "", gold=gold, ok=pred == gold, parse_confidence=conf)
            elif cat == "math":
                pred, conf = extract_gsm_number_conf(text)
                gold, _ = extract_gsm_number_conf(item["answer"])
                row.update(pred=pred, gold=gold, ok=pred is not None and pred == gold, parse_confidence=conf)
            elif cat == "instruct":
                row.update(ok=item_ok(item, text), pred=text[:120], parse_confidence="not_applicable")
            elif cat == "code":
                row.update(ok=_run_humaneval(item["prompt"], text, item["test"], item["entry_point"]),
                           pred=text[:200], parse_confidence="not_applicable")
            else:
                ok, pred = _tool_answer_ok(item[0], row.get("tool_calls") or [], text)
                row.update(ok=ok, pred=pred, gold=item[0], parse_confidence="not_applicable")
    result["parser"] = PARSER_VERSION
    result["benchmark_manifest"] = manifest
    result["benchmark_fingerprint"] = manifest["fingerprint"]
    result["categories"] = {cat: category_score(rows) for cat, rows in result["items"].items()}
    result["stats"] = {cat: category_stats(rows) for cat, rows in result["items"].items()}
    result["overall"]["score"] = overall_score(result["categories"]) if any(
        v is not None for v in result["categories"].values()) else None
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


def export_evalplus(document: dict) -> list[dict]:
    from .code import assemble_candidate
    tasks = {item["task_id"]: item for item in read_jsonl("humaneval.jsonl")}
    source_hash = (document.get("benchmark_manifest") or {}).get("data_sha256", {}).get("humaneval.jsonl")
    current_hash = benchmark_manifest(document.get("limit"))["data_sha256"]["humaneval.jsonl"]
    if source_hash != current_hash:
        raise ValueError("HumanEval source identity is missing or differs; refusing to export mismatched prompts")
    samples = []
    for row in (document.get("items") or {}).get("code", []):
        key = str(row.get("task_id") or row.get("key") or row.get("id"))
        if key not in tasks:
            raise ValueError(f"unknown HumanEval task {key}")
        completion = _strip_reasoning(str(row.get("source_text", row.get("raw_text")) or ""))
        samples.append({"task_id": key, "solution": assemble_candidate(tasks[key]["prompt"], completion, tasks[key]["entry_point"])})
    if not samples:
        raise ValueError("result contains no code completions")
    return samples


def main(argv: list[str], *, export: bool = False) -> int:
    parser = argparse.ArgumentParser(prog="sixcat export-evalplus" if export else "sixcat rescore")
    parser.add_argument("result", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-minutes", type=float, default=30, help="Offline grading deadline; 0 means unlimited.")
    args = parser.parse_args(argv)
    if args.out.resolve() == args.result.resolve() or args.out.exists():
        parser.error("use a NEW output file; the source and existing outputs are never overwritten")
    try:
        document = load_result(args.result)
        if export:
            samples = export_evalplus(document)
            atomic_write_text(args.out, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in samples))
            print(f"exported {len(samples)} saved completions; this does NOT run EvalPlus or report a HumanEval+ score")
        else:
            from .journal import TimeBudget
            from .runtime import deadline_scope
            budget = TimeBudget(None if args.max_minutes == 0 else args.max_minutes * 60)
            with deadline_scope(budget.deadline):
                result = regrade(document)
            result["regrade_provenance"] = {"kind": "offline-no-new-generations", "source": str(args.result),
                "source_sha256": hashlib.sha256(args.result.read_bytes()).hexdigest(),
                "source_parser": document["parser"], "source_benchmark_fingerprint": document.get("benchmark_fingerprint")}
            atomic_write_json(args.out, result)
            print(f"rescored saved first responses into {args.out}; no model requests were made")
    except (OSError, ValueError, KeyError, TimeoutError) as exc:
        parser.error(str(exc))
    return 0
