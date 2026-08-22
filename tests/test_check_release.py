from __future__ import annotations

from pathlib import Path

from tests.test_hermes_skill import _load_script


def test_compare_release_detects_newer_and_dev_checkouts():
    check = _load_script("check_release.py")
    assert check.compare_release("0.4.2", "v0.4.3") == "update_available"
    assert check.compare_release("0.4.3", "v0.4.2") == "newer_than_release"
    assert check.compare_release("0.4.2", "v0.4.2") == "current"


def test_build_report_flags_update_and_lists_commands(tmp_path: Path):
    check = _load_script("check_release.py")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.4.2"\n', encoding="utf-8")

    def fake_fetch(*, timeout=5.0):
        return {
            "tag_name": "v0.4.3",
            "html_url": "https://github.com/vcruz305/sixcat-eval/releases/tag/v0.4.3",
        }

    report = check.build_report(root=tmp_path, fetch_fn=fake_fetch)
    assert report["update_available"] is True
    assert report["latest_tag"] == "v0.4.3"
    assert report["local_version"] == "0.4.2"
    assert check.update_commands("v0.4.3") == [
        "git fetch origin --tags",
        "git checkout v0.4.3",
        "python -m pip install -e .",
    ]


def test_build_report_fails_open_on_network_error(tmp_path: Path):
    check = _load_script("check_release.py")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.4.2"\n', encoding="utf-8")

    def boom(*, timeout=5.0):
        raise TimeoutError("no network")

    report = check.build_report(root=tmp_path, fetch_fn=boom)
    assert report["status"] == "skipped"
    assert report["update_available"] is False
    assert "no network" in report["reason"]
