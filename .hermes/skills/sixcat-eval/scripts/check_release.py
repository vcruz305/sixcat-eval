"""Compare this checkout to the latest GitHub release. Fail open on network errors."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REPO = "vcruz305/sixcat-eval"
DEFAULT_API = f"https://api.github.com/repos/{DEFAULT_REPO}/releases/latest"
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def parse_version(value: str) -> tuple[int, int, int] | None:
    text = value.strip()
    if text.lower().startswith("v"):
        text = text[1:]
    match = _VERSION_RE.match(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def read_local_version(root: Path = PROJECT_ROOT) -> str:
    pyproject = root / "pyproject.toml"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version") and "=" in stripped:
            _, _, raw = stripped.partition("=")
            return raw.strip().strip("\"'")
    raise ValueError(f"cannot read version from {pyproject}")


def fetch_latest_release(url: str = DEFAULT_API, timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "sixcat-eval-skill"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub latest-release payload must be an object")
    return payload


def compare_release(local: str, latest: str) -> str:
    local_parts = parse_version(local)
    latest_parts = parse_version(latest)
    if local_parts is None or latest_parts is None:
        return "unknown"
    if latest_parts > local_parts:
        return "update_available"
    if latest_parts < local_parts:
        return "newer_than_release"
    return "current"


def build_report(
    *,
    root: Path = PROJECT_ROOT,
    fetch_fn=fetch_latest_release,
    timeout: float = 5.0,
) -> dict[str, Any]:
    local = read_local_version(root)
    report: dict[str, Any] = {
        "status": "ok",
        "local_version": local,
        "latest_tag": None,
        "latest_version": None,
        "latest_url": None,
        "comparison": "unknown",
        "update_available": False,
        "repo": DEFAULT_REPO,
    }
    try:
        payload = fetch_fn(timeout=timeout)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        report["status"] = "skipped"
        report["reason"] = f"release check failed: {exc}"
        return report
    if not isinstance(payload, dict):
        report["status"] = "skipped"
        report["reason"] = "release check failed: payload is not an object"
        return report
    tag = str(payload.get("tag_name") or "").strip()
    report["latest_tag"] = tag or None
    report["latest_version"] = tag[1:] if tag.lower().startswith("v") else (tag or None)
    report["latest_url"] = payload.get("html_url") or f"https://github.com/{DEFAULT_REPO}/releases/latest"
    report["comparison"] = compare_release(local, tag)
    report["update_available"] = report["comparison"] == "update_available"
    return report


def update_commands(tag: str) -> list[str]:
    return [
        "git fetch origin --tags",
        f"git checkout {tag}",
        "python -m pip install -e .",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check this Sixcat checkout against the latest GitHub release.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    report = build_report(timeout=args.timeout)
    if report.get("update_available") and report.get("latest_tag"):
        report["update_commands"] = update_commands(str(report["latest_tag"]))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"local={report['local_version']} latest={report.get('latest_tag') or 'n/a'} "
            f"comparison={report['comparison']} status={report['status']}"
        )
        if report.get("update_available"):
            print("update available:", report.get("latest_url"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
