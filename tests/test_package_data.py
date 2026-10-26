from __future__ import annotations

from pathlib import Path

import sixcat
from sixcat.dataio import DATA, read_jsonl


REQUIRED_DATASETS = {
    "humaneval.jsonl",
    "ifeval.jsonl",
    "ifeval_100.jsonl",
    "tiny_arc.jsonl",
    "tiny_gsm8k.jsonl",
    "tiny_hellaswag.jsonl",
    "tiny_mmlu.jsonl",
    "tiny_truthfulqa.jsonl",
    "tiny_winogrande.jsonl",
}


def test_runtime_datasets_are_package_relative_and_readable():
    package_root = Path(sixcat.__file__).resolve().parent
    assert DATA == package_root / "data"
    assert {path.name for path in DATA.glob("*.jsonl")} == REQUIRED_DATASETS
    for name in sorted(REQUIRED_DATASETS):
        assert read_jsonl(name), f"{name} must ship with at least one row"


def test_pyproject_declares_dataset_package_data():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'sixcat = ["model-policies.json", "data/*.jsonl"]' in text
    import tomllib
    dependencies = tomllib.loads(text)["project"]["dependencies"]
    assert "langdetect>=1.0.9,<2" in dependencies
    assert "httpx>=0.28.1,<1" in dependencies


def test_sdist_manifest_includes_the_complete_test_package():
    root = Path(__file__).resolve().parents[1]
    text = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include tests *.py" in text
    assert "recursive-include tools *.py" in text
    assert (root / "tools" / "__init__.py").is_file()


def test_release_version_matches_skill_readme_and_notes():
    import tomllib
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    skill = (root / ".hermes/skills/sixcat-eval/SKILL.md").read_text(encoding="utf-8")
    assert f"version: {version}\n" in skill.split("\n---\n", 1)[0]
    assert f"releases/tag/v{version}" in (root / "README.md").read_text(encoding="utf-8")
    assert (root / "RELEASE_NOTES.md").read_text(encoding="utf-8").startswith(f"# SixCat {version} ")


def test_hermes_console_entrypoint_and_readme_workflow_are_packaged():
    import tomllib
    from sixcat import hermes
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["scripts"]["sixcat-hermes"] == "sixcat.hermes:main"
    assert callable(hermes.main)
    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "docs/hermes.md").read_text(encoding="utf-8")
    for command in ("inspect", "smoke", "preflight", "run"):
        assert f"-m sixcat.hermes {command}" in guide
    assert "--query-file sixcat-controller.txt" in guide
    assert "docs/hermes.md" in readme
    assert (root / "docs/hermes-nous.md").is_file()
