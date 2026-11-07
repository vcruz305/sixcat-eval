# Score contract

| Category | Source | Standard count | Verdict |
|---|---|---:|---|
| Knowledge | tinyMMLU, tinyARC, tinyHellaSwag, tinyWinogrande | 20 total | Presented-choice letter match |
| Math | tinyGSM8K | 20 | Exact normalized final number |
| Truth | tinyTruthfulQA MC1 | 20 | Presented-choice letter match |
| Instruct | IFEval-100 | 20 | All item constraints pass |
| Code | HumanEval | 20 | One saved generation, guarded local checker |
| Tools | Structured function-call challenges | 20 | Typed arguments, exact order/count, or abstention |

Each category is `100 * correct / scored`. Overall is the unweighted mean of nonempty category scores. **A partial result is labeled incomplete and is not comparable by default.** Missing items are not silently counted as model failures. The three no-tool challenges test abstention, not the correctness of their free-text answers.

Parser **v5** rejects option letters outside the displayed choices, does not confuse words such as “definitely” with option D, marks conflicting answers ambiguous, strips incomplete inline thinking, and parses full supported numeric expressions instead of accepting their prefixes. Tool arguments distinguish JSON booleans from numbers. These results are not silently comparable with parser-v4 results.

## First responses stay first

The headline score never improves merely because you selectively reran failures. The journal keeps every attempt and the first scored response separately. Later samples are displayed only in a **latest-attempt diagnostic, not pass@1**. Network failures do not become FAILs. When an answer arrived but its local grader was interrupted, resume reuses that saved completion rather than obtaining a new one.

```bash
# Continue unfinished items, retaining all original scored answers.
python -m sixcat \
  --base-url http://127.0.0.1:8085/v1 --model my-model \
  --artifact-id my-model-Q4-release-1 --policy strict --concurrency 4 \
  --max-minutes 30 --out results/my-model-q4.json --retry remaining
```

`--retry failed` and `--retry incomplete` still exist for diagnostics. They do not replace first-response headline verdicts. `python -m sixcat retry-plan RESULT.json --retry remaining --json` reconstructs the model, endpoint, policy, budgets, artifact identity and relevant options. Old journals need fresh output paths because the scoring and identity contracts changed.
