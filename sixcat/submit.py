"""Preview/export a saved evaluation; publish only with explicit approval."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from .community import (META_FIELDS, MAX_BYTES, SubmissionError, require, read_json, strict_json,
                        validate_result, check_tree)
from .community_export import default_metadata, make_public, validate_public, result_path, render_table
from .storage import atomic_write_json


def parser():
    p = argparse.ArgumentParser(prog="sixcat submit", description=__doc__, allow_abbrev=False)
    p.add_argument("result", type=Path, help="Saved local result or previously exported public JSON")
    action = p.add_mutually_exclusive_group()
    action.add_argument("--preview", action="store_true", help="Offline preview only; no writes or GitHub requests")
    action.add_argument("--export-dir", type=Path, help="Write a local submission package only")
    action.add_argument("--yes", action="store_true", help="Explicitly authorize public JSON, branch/fork and PR creation")
    p.add_argument("--github-user", help="Contributor username; publishing verifies it against gh's authenticated user")
    p.add_argument("--metadata", type=Path, help="Public model/runtime metadata JSON object; never a credentials file")
    p.add_argument("--include-reasoning", action="store_true", help="Include saved reasoning text; omitted by default")
    p.add_argument("--run-at", help="Override missing run date with an ISO-8601 timestamp")
    p.add_argument("--json", action="store_true")
    for field in META_FIELDS:
        p.add_argument("--" + field.replace("_", "-"), type=(int if field == "context_tokens" else float if field in {"average_bpw", "weight_size_gib"} else str))
    return p


def build_document(args, raw, original_hash, contributor):
    if raw.get("schema") == "sixcat-community-v1":
        validate_public(raw)
        require(not args.metadata and not args.run_at and not args.include_reasoning and
                not any(getattr(args, f) is not None for f in META_FIELDS),
                "A prepared public JSON is immutable; change metadata by re-exporting the original result")
        require(not contributor or contributor.casefold() == raw["contributor"].casefold(), "Contributor mismatch")
        return raw
    validate_result(raw)
    meta = default_metadata(raw)
    if args.metadata:
        overrides = read_json(args.metadata)
        require(isinstance(overrides, dict) and set(overrides) <= set(META_FIELDS), "Invalid metadata fields")
        meta.update(overrides)
    for field in META_FIELDS:
        value = getattr(args, field)
        if value is not None:
            meta[field] = value
    if meta["source_kind"] == "cloud":
        for key in ("inference_engine", "engine_version", "quant_format", "quant_precision"):
            if meta[key] == "Unknown":
                meta[key] = "Undisclosed"
    missing = [k for k in ("source_kind", "source") if not meta.get(k)]
    if not contributor:
        missing.append("github_user")
    if missing:
        return {"schema": "sixcat-submission-draft-v1", "status": "needs_metadata", "missing": missing,
                "metadata": meta, "score": raw["overall"], "counts": raw["n"],
                "instructions": "Supply only missing metadata to sixcat submit; the original result is untouched."}
    times = [row.get("ts") for rows in raw["items"].values() for row in rows
             if type(row.get("ts")) in (int, float)]
    when = args.run_at or datetime.fromtimestamp(max(times) if times else args.result.stat().st_mtime,
                                               timezone.utc).isoformat()
    return make_public(raw, contributor=contributor, metadata=meta, run_at=when,
                       original_sha256=original_hash, include_reasoning=args.include_reasoning)


def write_package(doc, directory):
    if doc.get("schema") == "sixcat-community-v1":
        validate_public(doc)
    require(not directory.is_symlink(), "Submission directory cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    if doc.get("status") == "needs_metadata":
        path = directory / "metadata-draft.json"
    else:
        path = directory / Path(result_path(doc)).name
    if path.exists():
        require(read_json(path) == doc, "A different export exists; choose a fresh directory")
        return path
    require(not any(p.name != "metadata-draft.json" for p in directory.iterdir()),
            "Export directory contains other files; choose a fresh directory")
    atomic_write_json(path, doc)
    if doc.get("schema") == "sixcat-community-v1":
        with (directory / "README-row.md").open("x", encoding="utf-8") as handle:
            handle.write(render_table([doc]))
        instructions = (
            "Review the public JSON and its saved answers. To publish this exact export, run:\n"
            f'python -m sixcat submit "{path.name}" --yes\n'
            "No GitHub upload has occurred. The repository README is regenerated from upstream on submission.\n",
            )
        with (directory / "SUBMISSION.txt").open("x", encoding="utf-8") as handle:
            handle.write(instructions[0] if isinstance(instructions, tuple) else instructions)
    return path


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        require(args.result.is_file() and not args.result.is_symlink(), "Result must be a regular file")
        with args.result.open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
        raw = strict_json(data)
        require(isinstance(raw, dict), "Result must be an object")
        if raw.get("schema") == "sixcat-community-v1":
            validate_public(raw)
        else:
            validate_result(raw)
        publish_requested = args.yes
        if not (args.preview or args.export_dir or args.yes) and sys.stdin.isatty() and sys.stdout.isatty():
            answer = input("Publish saved answers, model/configuration and your GitHub username in a public Sixcat PR? [submit/preview/private] ").strip().lower()
            if answer not in {"submit", "preview"}:
                print("Kept private. Original result unchanged.")
                return 0
            publish_requested = answer == "submit"
            args.preview = answer == "preview"
        client = None
        contributor = args.github_user or raw.get("contributor")
        if publish_requested:
            from .community_github import GitHubCLI
            client = GitHubCLI()
            actor = client.username()
            require(not contributor or contributor.casefold() == actor.casefold(), "Contributor must match gh's authenticated user")
            contributor = actor
        doc = build_document(args, raw, hashlib.sha256(data).hexdigest(), contributor)
        if args.preview:
            print(json.dumps(doc, indent=2, ensure_ascii=False))
            return 2 if doc.get("status") == "needs_metadata" else 0
        directory = args.export_dir or args.result.parent / (args.result.stem + ".submission")
        exported = write_package(doc, directory)
        if doc.get("status") == "needs_metadata":
            print(json.dumps({"status": "needs_metadata", "missing": doc["missing"], "draft": str(exported)}))
            return 2
        if publish_requested:
            from .community_github import publish
            result = publish(doc, consent=True, client=client)
            result["local_export"] = str(exported)
        else:
            result = {"status": "exported_only", "local_export": str(exported),
                      "repository_path": result_path(doc), "public": False}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (SubmissionError, OSError, ValueError, TypeError, KeyError) as exc:
        message = str(exc) if isinstance(exc, SubmissionError) else "Cannot prepare submission; inspect the local result and metadata"
        print("Sixcat submission: " + message, file=sys.stderr)
        return 2


def after_run(result, path, *, interactive=False):
    """The benchmark is already saved. Submission failure never changes its exit status."""
    try:
        validate_result(result)
    except (SubmissionError, OSError, ValueError):
        return
    print(f'Community Results: 120/120 scored. Preview/export with: python -m sixcat submit "{path}" --preview')
    if interactive:
        try:
            main([str(path)])
        except (EOFError, KeyboardInterrupt):
            print("Submission cancelled; result kept private.")
    else:
        # Draft/export only: this never reads GitHub credentials or uploads.
        main([str(path), "--export-dir", str(path.parent / (path.stem + ".submission"))])


if __name__ == "__main__":
    raise SystemExit(main())
