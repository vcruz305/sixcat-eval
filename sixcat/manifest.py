"""Content-addressed benchmark and separately observed server identity."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from .dataio import DATA, read_jsonl
from .selection import (
    CODE_CHALLENGE_IDS, KNOWLEDGE_CHALLENGE_INDICES, MATH_CHALLENGE_INDICES,
    TRUTH_CHALLENGE_INDICES, INSTRUCT_CHALLENGE_INDICES, SELECTION_PROFILE,
    select_indexed_by_indices, select_by_ids, select_by_indices,
)

ATTEMPT_POLICY = "first-scored-response-v1"
SCHEDULE = "balanced-hardest-first-v1"
DATASETS = ("tiny_mmlu.jsonl", "tiny_arc.jsonl", "tiny_hellaswag.jsonl",
            "tiny_winogrande.jsonl", "tiny_gsm8k.jsonl", "tiny_truthfulqa.jsonl",
            "ifeval_100.jsonl", "humaneval.jsonl")
SCORING_SOURCES = ("score.py", "instruct.py", "code.py", "tools.py", "run.py",
                   "selection.py", "receipts.py", "client.py", "manifest.py", "offline.py", "generation.py", "parsing.py")

def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def selected_keys(limit: int | None, skip_code_exec: bool = False) -> dict[str, list[str]]:
    from .tools import ITEMS
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    limits = [None] * 4 if limit is None else [limit // 4 + (i < limit % 4) for i in range(4)]
    knowledge = []
    for source, filename, cap in zip(("mmlu", "arc", "hellaswag", "winogrande"), DATASETS[:4], limits):
        knowledge.extend(f"{source}:{i}" for i, _ in select_indexed_by_indices(
            read_jsonl(filename), cap, KNOWLEDGE_CHALLENGE_INDICES[source]))
    return {
        "knowledge": knowledge,
        "math": [f"gsm:{i}" for i, _ in select_indexed_by_indices(read_jsonl(DATASETS[4]), limit, MATH_CHALLENGE_INDICES)],
        "truth": [f"tqa:{i}" for i, _ in select_indexed_by_indices(read_jsonl(DATASETS[5]), limit, TRUTH_CHALLENGE_INDICES)],
        "instruct": [f"ifeval:{item['key']}" for item in select_by_indices(read_jsonl(DATASETS[6]), limit, INSTRUCT_CHALLENGE_INDICES)],
        "code": [] if skip_code_exec else [item["task_id"] for item in select_by_ids(
            read_jsonl(DATASETS[7]), limit, CODE_CHALLENGE_IDS, key=lambda item: item["task_id"])],
        "tools": [f"tool:{item[0]}" for item in (ITEMS if limit is None else ITEMS[:limit])],
    }

def expected_counts(limit: int | None, skip_code_exec: bool = False) -> dict[str, int]:
    return {cat: len(keys) for cat, keys in selected_keys(limit, skip_code_exec).items()}

def benchmark_manifest(limit: int | None, skip_code_exec: bool = False) -> dict:
    from .tools import ITEMS, TOOLS
    root = Path(__file__).resolve().parent
    manifest = {
        "version": "sixcat-manifest-v1", "selection_profile": SELECTION_PROFILE,
        "selected_keys": selected_keys(limit, skip_code_exec),
        "data_sha256": {name: hashlib.sha256((DATA / name).read_text(encoding="utf-8").encode()).hexdigest() for name in DATASETS},
        "scorer_sha256": {name: hashlib.sha256((root / name).read_text(encoding="utf-8").encode()).hexdigest() for name in SCORING_SOURCES},
        "tools_sha256": fingerprint({"schema": TOOLS, "items": ITEMS}),
    }
    return {**manifest, "fingerprint": fingerprint(manifest)}

def observed_server_identity(server_props: dict, model: str) -> dict:
    """Only stable advertised fields, never credentials or transient slot state.

    Server-advertised identity is evidence, not attestation of the actual weights.
    The optional CLI artifact ID is recorded separately as operator-provided.
    """
    props = server_props.get("llama_cpp_props") or {}
    models = server_props.get("openai_models") or {}
    matches = [item for item in models.get("data", [])
               if isinstance(item, dict) and item.get("id") == model] if isinstance(models, dict) else []
    result = {}
    if len(matches) == 1:
        row = matches[0]
        result["advertised_model"] = {key: row[key] for key in (
            "id", "root", "parent", "model_revision", "tokenizer_revision", "max_model_len", "context_length"
        ) if key in row}
        upstream = row.get("sixcat_upstream")
        if row.get("target_kind") == "hermes_runtime_model" and isinstance(upstream, dict):
            required = ("provider", "model", "route_fingerprint")
            if all(isinstance(upstream.get(k), str) and upstream[k] for k in required) and upstream["model"] == model:
                result["verified_upstream"] = {k: upstream[k] for k in required}
    if isinstance(props, dict):
        for key in ("model_path", "chat_template", "model_alias", "build_info"):
            if props.get(key) is not None:
                result[key + "_sha256"] = fingerprint(props[key])
    return {"evidence": "server-advertised" if result else "unavailable", **result}
