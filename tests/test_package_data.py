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
    assert 'dependencies = ["langdetect>=1.0.9,<2"]' in text


def test_sdist_manifest_includes_the_complete_test_package():
    root = Path(__file__).resolve().parents[1]
    text = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include tests *.py" in text
    assert "recursive-include tools *.py" in text
    assert (root / "tools" / "__init__.py").is_file()
