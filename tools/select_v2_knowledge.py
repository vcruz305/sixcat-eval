"""Provenance for sixcat/data/v2_knowledge.jsonl (challenge-v2 Knowledge).

The twenty items are taken unchanged (apart from trimming stray whitespace)
from MMLU-Pro, https://github.com/TIGER-AI-Lab/MMLU-Pro (Apache-2.0), which
publishes per-question outputs for 48 model runs under `eval_results/`.

Selection was done in two steps, and the second step was manual:

1. Filter. Keep questions with ten distinct options, no reference to a figure
   or table, a moderate length, results from at least 44 of the published
   runs, and where
     * 10%-40% of the runs answered correctly,
     * 25%-70% of the sixteen strongest 2024-era runs answered correctly,
     * runs that answered correctly were markedly stronger overall than runs
       that did not (mean overall accuracy gap of at least 0.15), and
     * the one 2026 frontier run in the set agreed with the answer key.
   This aims at questions that are hard but whose key a strong independent
   solver confirms; it deliberately does NOT pick "whatever models fail most",
   which is how mislabeled items concentrate in a challenge set.

2. Review. Candidates were read one by one and the key re-derived by hand.
   Items with a wrong or debatable key, a key option formatted differently
   from its distractors, garbled text, or a dependency on a specific textbook
   were dropped. The twenty question ids kept are listed in SELECTED below.

    python tools/select_v2_knowledge.py /path/to/MMLU-Pro            # rewrite
    python tools/select_v2_knowledge.py /path/to/MMLU-Pro --check    # compare
    python tools/select_v2_knowledge.py /path/to/MMLU-Pro --band     # list step-1 candidates

Options are shown to the model in their published order (answer positions are
already spread across A-J, and some options refer to other options by letter).
"""
from __future__ import annotations

import argparse
import ast
import json
import statistics
import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "sixcat" / "data" / "v2_knowledge.jsonl"
FRONTIER = "gemini-3.1-pro_5-shots"

SELECTED = [
    "688", "5118", "1510", "1404", "1895", "4608", "4444", "10223", "10297", "10092",
    "6255", "6605", "6348", "3404", "7372", "10687", "10656", "7510", "10856", "2333",
]


def load(root: Path):
    questions: dict[str, dict] = {}
    matrix: dict[str, dict[str, bool]] = {}
    for archive in sorted((root / "eval_results").glob("*.zip")):
        model = archive.name.replace("model_outputs_", "").split(".zip")[0].replace(".json", "")
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not name.endswith(".json") or "__MACOSX" in name or "summary" in name:
                    continue
                data = json.loads(bundle.read(name))
                for row in data if isinstance(data, list) else []:
                    if not isinstance(row, dict) or "question_id" not in row:
                        continue
                    qid = str(row["question_id"])
                    questions.setdefault(qid, row)
                    matrix.setdefault(qid, {})[model] = row.get("pred") == row.get("answer")
    return questions, matrix


def options_of(row: dict) -> list[str]:
    options = row["options"]
    return ast.literal_eval(options) if isinstance(options, str) else list(options)


def band(questions, matrix) -> list[dict]:
    models = sorted({model for row in matrix.values() for model in row})
    accuracy = {m: statistics.mean(1.0 if row.get(m) else 0.0 for row in matrix.values() if m in row)
                for m in models}
    strong = [m for m in models if accuracy[m] >= 0.62 and m != FRONTIER]
    out = []
    for qid, row in matrix.items():
        if len(row) < 44 or not row.get(FRONTIER):
            continue
        record = questions[qid]
        options = options_of(record)
        text = record["question"]
        if len(options) != 10 or len(set(options)) != 10 or len(text) > 900 or any(len(o) > 220 for o in options):
            continue
        if any(word in text.lower() for word in ("figure", "diagram", "shown below", "the table", "graph above", "image")):
            continue
        others = {m: ok for m, ok in row.items() if m != FRONTIER}
        right = [accuracy[m] for m, ok in others.items() if ok]
        wrong = [accuracy[m] for m, ok in others.items() if not ok]
        if len(right) < 3 or len(wrong) < 3:
            continue
        p_all = len(right) / len(others)
        p_strong = statistics.mean(1.0 if row.get(m) else 0.0 for m in strong if m in row)
        gap = statistics.mean(right) - statistics.mean(wrong)
        if 0.10 <= p_all <= 0.40 and 0.25 <= p_strong <= 0.70 and gap >= 0.15:
            out.append({"question_id": qid, "category": record["category"], "p_all": round(p_all, 3),
                        "p_strong": round(p_strong, 3), "gap": round(gap, 3)})
    return sorted(out, key=lambda item: -item["gap"])


def rows(questions) -> list[dict]:
    result = []
    for qid in SELECTED:
        record = questions[qid]
        options = [option.strip() for option in options_of(record)]
        answer = int(record["answer_index"])
        if "ABCDEFGHIJ"[answer] != record["answer"] or len(options) != 10:
            raise ValueError(f"{qid}: inconsistent key")
        result.append({"key": f"mmlupro:{qid}", "category": record["category"], "src": record["src"],
                       "question": record["question"].strip(), "choices": options, "answer": answer})
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mmlu_pro", type=Path, help="path to a checkout of TIGER-AI-Lab/MMLU-Pro")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--band", action="store_true", help="print the step-1 candidate list and exit")
    args = parser.parse_args(argv)
    questions, matrix = load(args.mmlu_pro)
    if args.band:
        candidates = band(questions, matrix)
        chosen = {item["question_id"] for item in candidates} & set(SELECTED)
        print(json.dumps(candidates, indent=1))
        print(f"{len(candidates)} candidates; {len(chosen)}/{len(SELECTED)} selected ids are in the band", file=sys.stderr)
        return 0
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows(questions))
    if args.check:
        if OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} differs from the selection output", file=sys.stderr)
            return 1
        print(f"{OUT.name}: up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(SELECTED)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
