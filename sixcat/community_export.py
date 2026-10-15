"""Allowlisted public copies, stable filenames and README rendering."""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import html
import ipaddress
import re
from urllib.parse import urlsplit

from .community import (SCHEMA, START, END, META_FIELDS, RESULT_FIELDS, ROW_FIELDS,
    SEGMENT_FIELDS, USERNAME, HEX, PRIVATE, SubmissionError, require, object_keys,
    check_tree, validate_result)
from .manifest import fingerprint
from .score import CATEGORIES


def default_metadata(result):
    supplied = result.get("community_metadata") or {}
    meta = {k: supplied[k] for k in META_FIELDS if k in supplied} if isinstance(supplied, dict) else {}
    meta.setdefault("model_name", result.get("model", "Unknown"))
    if not meta.get("source_kind"):
        host = urlsplit(str(result.get("base_url") or "")).hostname or ""
        local = host in {"localhost", "127.0.0.1", "::1"}
        try:
            local = local or ipaddress.ip_address(host).is_private
        except ValueError:
            pass
        if local:
            meta.update(source_kind="local", source="local")
    cloud = meta.get("source_kind") == "cloud"
    for k in ("quant_format", "quant_precision", "inference_engine", "engine_version"):
        meta.setdefault(k, "Undisclosed" if cloud else "Unknown")
    meta.setdefault("api_wrapper", "Unknown")
    meta.setdefault("wrapper_version", "Unknown")
    meta.setdefault("evaluation_client", "Sixcat direct HTTP")
    for k in META_FIELDS:
        meta.setdefault(k, None)
    return meta


def validate_metadata(meta):
    object_keys(meta, META_FIELDS, required=META_FIELDS)
    for k, v in meta.items():
        if v is None:
            continue
        if k in {"context_tokens", "weight_size_gib", "average_bpw"}:
            require(type(v) in (int, float) and v > 0, "Invalid numeric model metadata")
            if k == "context_tokens":
                require(type(v) is int, "Context size must be an integer")
        else:
            require(isinstance(v, str) and 0 < len(v) <= 240 and not any(ord(c) < 32 for c in v),
                    "Invalid model metadata text")
            require(not PRIVATE.search(v), "Private filesystem path in public metadata")
        if k.endswith("_url"):
            u = urlsplit(v)
            require(u.scheme == "https" and u.hostname and "." in u.hostname and not u.username
                    and not u.password and not u.query and not u.fragment, "Model links must be public HTTPS URLs")
            require(not u.hostname.endswith((".local", ".internal")), "Private model URL")
            try:
                ipaddress.ip_address(u.hostname)
            except ValueError:
                pass
            else:
                raise SubmissionError("Use public hostname links, not IP addresses")
    require(meta["source_kind"] in {"cloud", "local"} and meta["source"],
            "Specify source-kind cloud/local and source provider or local")
    for k in ("model_name", "quant_format", "quant_precision", "inference_engine", "engine_version",
              "api_wrapper", "wrapper_version", "evaluation_client"):
        require(bool(meta[k]), f"Missing metadata: {k}")


def project_result(raw, include_reasoning=False):
    r = {k: copy.deepcopy(raw[k]) for k in RESULT_FIELDS if k in raw}
    r["items"] = {c: [{k: copy.deepcopy(row[k]) for k in ROW_FIELDS if k in row
                       and (k != "reasoning_content" or include_reasoning)} for row in raw["items"][c]] for c in CATEGORIES}
    r["execution_segments"] = [{k: s[k] for k in SEGMENT_FIELDS if k in s} for s in raw["execution_segments"]]
    return r


def run_identity(result):
    # Filename, contributor, export date and optional reasoning do not create new runs.
    identity = copy.deepcopy(result)
    for rows in identity["items"].values():
        for row in rows:
            row.pop("reasoning_content", None)
    return fingerprint(identity)


def slug(value, limit=48):
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:limit].rstrip("-") or "unknown"


def parse_time(value):
    require(isinstance(value, str), "Run time must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None and 2000 <= parsed.year <= 2100, "Invalid run time")
        return parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise SubmissionError("Invalid ISO-8601 run time") from exc


def result_path(doc):
    when = parse_time(doc["run_at"])
    m = doc["metadata"]
    source = {"nous portal": "nous", "openrouter": "or", "local/self-hosted": "local"}.get(m["source"].casefold(), m["source"])
    quant = m["quant_format"] + ("-" + m["quant_precision"] if m["quant_precision"] not in {"Unknown", "Undisclosed"} else "")
    name = "__".join((slug(doc["result"]["model"]), slug(source, 24), slug(quant, 32),
                      doc["contributor"].lower(), when.strftime("%Y%m%dT%H%M%SZ"), doc["run_id"][:12])) + ".json"
    return f"community/results/{when:%Y/%m}/{name}"


def make_public(raw, *, contributor, metadata, run_at, original_sha256, include_reasoning=False, registry=None):
    validate_result(raw, registry)
    r = project_result(raw, include_reasoning)
    date = parse_time(run_at).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"schema": SCHEMA, "run_id": run_identity(r), "run_at": date,
           "contributor": contributor, "metadata": metadata, "metadata_evidence": "contributor-reported",
           "result": r, "export": {"original_sha256": original_sha256,
           "reasoning_included": bool(include_reasoning), "answers_included": True,
           "omitted": ["endpoint URLs", "server properties", "local paths/profiles", "wire requests/prompts",
                       "provider errors", "latest-attempt diagnostics", "grader internals"] + ([] if include_reasoning else ["reasoning text"])}}
    doc["content_sha256"] = fingerprint(doc)
    validate_public(doc, registry=registry)
    return doc


def validate_public(doc, *, registry=None):
    fields = {"schema", "run_id", "run_at", "contributor", "metadata", "metadata_evidence", "result", "export", "content_sha256"}
    object_keys(doc, fields, required=fields)
    check_tree(doc, public=True)
    require(doc["schema"] == SCHEMA, "Unsupported public schema")
    require(isinstance(doc["contributor"], str) and USERNAME.fullmatch(doc["contributor"]), "Invalid GitHub username")
    require(doc["metadata_evidence"] == "contributor-reported", "Unsupported metadata evidence claim")
    parse_time(doc["run_at"])
    validate_metadata(doc["metadata"])
    r = doc["result"]
    object_keys(r, RESULT_FIELDS)
    validate_result(r, registry)
    require(not PRIVATE.search(r["model"]), "Private model path; do not publish private identifiers")
    for c in CATEGORIES:
        for row in r["items"][c]:
            object_keys(row, ROW_FIELDS)
    for s in r["execution_segments"]:
        object_keys(s, SEGMENT_FIELDS)
    object_keys(doc["export"], {"original_sha256", "reasoning_included", "answers_included", "omitted"},
                required={"original_sha256", "reasoning_included", "answers_included", "omitted"})
    require(isinstance(doc["export"]["original_sha256"], str) and HEX.fullmatch(doc["export"]["original_sha256"]), "Invalid original checksum")
    require(type(doc["export"]["reasoning_included"]) is bool and doc["export"]["answers_included"] is True, "Missing export disclosure")
    if not doc["export"]["reasoning_included"]:
        require(all("reasoning_content" not in row for rows in r["items"].values() for row in rows), "Undisclosed reasoning text")
    require(doc["run_id"] == run_identity(r), "Run identity mismatch")
    require(doc["content_sha256"] == fingerprint({k: v for k, v in doc.items() if k != "content_sha256"}), "Public checksum mismatch")


def markdown(value):
    text = html.escape(str(value), quote=True)
    for char in "\\`*_[]|":
        text = text.replace(char, f"&#{ord(char)};")
    return text.replace("\n", " ").replace("\r", " ")


def profile_key(doc):
    r = doc["result"]
    p = r["policy"]
    return (r["benchmark_fingerprint"], p["name"], p["thinking"], r["policy_fingerprint"])


def render_table(docs):
    if not docs:
        return "No community results submitted yet.\n"
    lines = []
    ordered = sorted(docs, key=lambda d: (profile_key(d), d["run_at"], d["run_id"]))
    last = None
    for d in ordered:
        group = profile_key(d)
        if group != last:
            if last is not None:
                lines.append("")
            lines.extend([f"#### {markdown(group[1])} · thinking {'on' if group[2] else 'off'} · policy `{group[3]}` · benchmark `{group[0][:12]}`", "",
                "| Model | Source | Quant | Engine / API | Overall | K / M / T / I / C / Tools | Contributor | Result |",
                "|---|---|---|---|---:|---|---|---|"])
            last = group
        m, r = d["metadata"], d["result"]
        quant = f"{m['quant_format']} {m['quant_precision']}"
        engine = f"{m['inference_engine']} {m['engine_version']} / {m['api_wrapper']} {m['wrapper_version']}"
        scores = " / ".join(f"{r['categories'][c]:.1f}" for c in CATEGORIES)
        lines.append(f"| {markdown(m['model_name'])} | {markdown(m['source_kind'] + ': ' + m['source'])} | {markdown(quant)} | {markdown(engine)} | {r['overall']['score']:.2f} | {scores} | @{d['contributor']} | [{d['run_at'][:10]}]({result_path(d)}) |")
    return "\n".join(lines) + "\n"


def replace_table(readme, docs):
    require(readme.count(START) == readme.count(END) == 1, "README requires exactly one managed Community Results block")
    before, rest = readme.split(START)
    old, after = rest.split(END)
    return before + START + "\n\n" + render_table(docs) + "\n" + END + after


def validate_collection(entries, registry=None):
    require(len(entries) <= 5000, "Too many community entries")
    seen = set()
    docs = []
    for path, doc in entries:
        validate_public(doc, registry=registry)
        require(path == result_path(doc), "Noncanonical submission filename/path")
        require(doc["run_id"] not in seen, "Duplicate run submission")
        seen.add(doc["run_id"])
        docs.append(doc)
    return docs
