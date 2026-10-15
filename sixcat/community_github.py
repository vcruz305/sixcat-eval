"""Consent-gated result PRs using existing GitHub CLI authentication."""
from __future__ import annotations
import base64
import json
import os
import re
import subprocess
import time
from urllib.parse import urlencode

from .community import MAX_BYTES, SubmissionError, USERNAME, require, strict_json
from .community_export import validate_collection, validate_public, result_path, replace_table

REPOSITORY = "vcruz305/sixcat-eval"
ROOT = "repos/" + REPOSITORY

class GitHubError(SubmissionError):
    def __init__(self, status=None):
        self.status = status
        super().__init__("GitHub operation failed" + (f" (HTTP {status})" if status else "") +
                         "; check gh authentication/permissions. Local result/export is unchanged.")

class GitHubCLI:
    def api(self, method, endpoint, data=None):
        args = ["gh", "api", "--hostname", "github.com", "--method", method, endpoint]
        if data is not None:
            args += ["--input", "-"]
        try:
            r = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                text=True, capture_output=True, timeout=60,
                env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_HOST": "github.com"})
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SubmissionError("GitHub CLI unavailable or timed out. Authenticate gh to publish; preview/export work offline.") from exc
        if r.returncode:
            status = re.search(r"HTTP (\d{3})", r.stderr or "")
            raise GitHubError(int(status[1]) if status else None)
        require(len(r.stdout) <= 24 * 1024 * 1024, "GitHub response exceeds limit")
        try:
            return json.loads(r.stdout) if r.stdout.strip() else None
        except ValueError as exc:
            raise SubmissionError("GitHub CLI returned invalid JSON") from exc

    def optional(self, endpoint):
        try:
            return self.api("GET", endpoint)
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise

    def username(self):
        name = self.api("GET", "user").get("login")
        require(isinstance(name, str) and USERNAME.fullmatch(name), "Invalid GitHub username")
        return name


def blob_text(client, sha):
    require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha), "Invalid Git blob identity")
    blob = client.api("GET", f"{ROOT}/git/blobs/{sha}")
    require(blob.get("encoding") == "base64" and blob.get("size", MAX_BYTES+1) <= MAX_BYTES,
            "Unsupported or oversized Git blob")
    try:
        data = base64.b64decode("".join(blob["content"].split()), validate=True)
        require(len(data) <= MAX_BYTES, "Git blob exceeds limit")
        return data.decode("utf-8")
    except (ValueError, UnicodeError, KeyError) as exc:
        raise SubmissionError("Invalid Git blob") from exc


def snapshot(client):
    sha = client.api("GET", f"{ROOT}/git/ref/heads/main")["object"]["sha"]
    commit = client.api("GET", f"{ROOT}/git/commits/{sha}")
    tree = client.api("GET", f"{ROOT}/git/trees/{commit['tree']['sha']}?recursive=1")
    require(tree.get("truncated") is False, "Truncated repository tree; refusing partial view")
    by_path = {entry["path"]: entry for entry in tree["tree"]}
    def read(path):
        entry = by_path.get(path, {})
        require(entry.get("mode") == "100644" and entry.get("type") == "blob", "Expected regular repository file")
        return blob_text(client, entry["sha"])
    registry = strict_json(read("sixcat/community-compatibility.json"))
    readme = read("README.md")
    paths = sorted(p for p in by_path if p.startswith("community/results/") and p.endswith(".json"))
    require(len(paths) <= 5000, "Community collection exceeds limit")
    require(sum(by_path[p].get("size", 0) for p in paths) <= 100 * 1024 * 1024, "Community collection size limit reached")
    docs = validate_collection([(p, strict_json(read(p))) for p in paths], registry)
    return sha, commit["tree"]["sha"], readme, docs, registry


def publish(doc, *, consent=False, client=None):
    require(consent is True, "Public submission requires explicit confirmation")
    client = client or GitHubCLI()
    actor = client.username()
    require(actor.casefold() == doc["contributor"].casefold(), "Contributor must match authenticated GitHub user")
    base, tree_sha, readme, docs, registry = snapshot(client)
    validate_public(doc, registry=registry)
    for old in docs:
        if old["run_id"] == doc["run_id"]:
            return {"status": "already_submitted", "url": f"https://github.com/{REPOSITORY}/blob/main/{result_path(old)}"}
    require(all(result_path(old) != result_path(doc) for old in docs), "Submission filename already exists")
    repo = client.api("GET", ROOT)
    writer = REPOSITORY if repo.get("permissions", {}).get("push") else actor + "/sixcat-eval"
    branch = "sixcat-results/" + doc["run_id"][:32]
    owner = writer.split("/")[0]
    existing = client.api("GET", ROOT + "/pulls?" + urlencode({"state": "all", "head": owner + ":" + branch, "base": "main"}))
    if existing:
        pr = existing[0]
        return {"status": "already_open" if pr["state"] == "open" else "already_closed", "url": pr["html_url"]}
    if writer != REPOSITORY:
        fork = client.optional("repos/" + writer)
        if fork is None:
            client.api("POST", ROOT + "/forks", {"default_branch_only": True})
            for _ in range(6):
                fork = client.optional("repos/" + writer)
                if fork:
                    break
                time.sleep(2)
        require(isinstance(fork, dict) and fork.get("fork") and
                fork.get("parent", {}).get("full_name") == REPOSITORY,
                "Contributor fork not ready or repository name already used; resolve it before retrying")
    destination = "repos/" + writer
    require(client.optional(destination + "/git/ref/heads/" + branch) is None,
            "A submission branch exists without a PR; inspect it in GitHub rather than overwrite it")
    files = [(result_path(doc), json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False) + "\n"),
             ("README.md", replace_table(readme, docs + [doc]))]
    tree = client.api("POST", destination + "/git/trees", {"base_tree": tree_sha,
        "tree": [{"path": path, "mode": "100644", "type": "blob", "content": content} for path, content in files]})
    commit = client.api("POST", destination + "/git/commits", {"message": "Add Sixcat community result " + doc["run_id"][:12],
        "tree": tree["sha"], "parents": [base]})
    require(client.api("GET", ROOT + "/git/ref/heads/main")["object"]["sha"] == base,
            "Upstream main changed; retry to regenerate the README table")
    client.api("POST", destination + "/git/refs", {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
    p, m = doc["result"]["policy"], doc["metadata"]
    body = ("## Community-reported result\n\n"
        f"Run: `{doc['run_id']}`\n\n"
        f"120/120 items, including 20 locally executed Code items. Policy: {p['name']}; thinking: {p['thinking']}.\n\n"
        "This PR adds one public JSON and regenerates the managed README table. "
        "Scores are saved first-response scores, not latest-attempt diagnostics. "
        "Metadata is contributor-reported; validation does not attest weights, billing or execution.\n\n"
        f"Saved answers included: yes. Reasoning text included: {doc['export']['reasoning_included']}. "
        "Local paths, endpoint URLs, profiles, wire requests and provider errors are omitted.\n\n"
        "The contributor explicitly approved public sharing. Review before merging.")
    pr = client.api("POST", ROOT + "/pulls", {"head": owner + ":" + branch, "base": "main",
        "title": "Community result: " + m["model_name"][:100] + " (" + doc["run_id"][:12] + ")",
        "body": body, "maintainer_can_modify": True})
    return {"status": "submitted", "url": pr["html_url"], "branch": branch,
            "files": [path for path, _ in files], "run_id": doc["run_id"]}
