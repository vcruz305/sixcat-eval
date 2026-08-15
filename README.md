# sixcat-eval

Six community LLM categories. One overall number. Minutes, not hours.

Point it at any OpenAI-compatible server (`llama-server`, vLLM, Ollama). It prints:

```text
category        score     n
----------------------------
knowledge        62.5    12
math             33.3     3
truth            66.7     3
instruct         33.3     3
code              0.0     3
tools            66.7     3
----------------------------
overall          43.8
```

**Overall is the unweighted mean of the category scores that actually ran.** Each category is `100 * n_correct / n`. Empty category → omitted from the mean, not a zero.

This is **not** a replacement for the full Open LLM Leaderboard, MixEval-Hard, or SWE-bench. It is the daily driver you can finish on a 24 GB card before lunch.

## What's in here

1. **[Score contract](#score-contract)** — six buckets, one average.
2. **[Categories](#categories)** — what each number is.
3. **[Quick start](#quick-start)** — one command against `:8085`.
4. **[Crash resume](#quick-start)** — live JSONL log + `--max-minutes`.
5. **[What we refuse to mix in](#what-we-refuse-to-mix-in)**

**Jump to:** [Install](#quick-start) · [Categories](#categories) · [Method](#method)

## Score contract

| Category | Source | Default n | Metric |
|---|---|---:|---|
| Knowledge | tinyMMLU + tinyARC + tinyHellaSwag + tinyWinogrande | 80 (20×4) | letter match |
| Math | tinyGSM8K | 20 | `####` number match |
| Truth | tinyTruthfulQA (mc1) | 20 | letter match |
| Instruct | IFEval | 20 | all listed constraints pass |
| Code | HumanEval | 20 | `pass@1` via local exec |
| Tools | 20 scripted function-call items | 20 | correct tool name (or none) |

tiny* sets are the 100-item IRT anchors from [tinyBenchmarks](https://github.com/felipemaiapolo/tinyBenchmarks) / [HF](https://huggingface.co/tinyBenchmarks). IFEval IDs follow [google-research/instruction_following_eval](https://github.com/google-research/google-research/tree/master/instruction_following_eval). HumanEval is the OpenAI set.

## Categories

**Knowledge** — four multiple-choice suites the Open LLM Leaderboard made standard. We do **not** feed the few-shot `input_formatted` blobs; zero-shot letter only.

**Math** — grade-school word problems. Parser takes `#### N` or the last number.

**Truth** — TruthfulQA mc1 (best true vs common myths).

**Instruct** — format constraints (no commas, all-caps, N bullets, `<<title>>`, placeholders, …). Unknown IFEval IDs do not fail the item. `language:response_language` is a non-empty check (no langdetect).

**Code** — HumanEval `pass@1`. Completions run in a temp process with an 8s cap. First 20 tasks only.

**Tools** — twenty prompts with a five-tool schema (`list_dir`, `read_file`, `search`, `add`, `write_file`). Two items require **no** tool. This is not Hermes loop-gate; for the 20-task agent harness use [hermes-agentic-bench](https://github.com/vcruz305/hermes-agentic-bench).

## Quick start

Python 3.11+. No extra packages.

```bash
git clone https://github.com/vcruz305/sixcat-eval
cd sixcat-eval

python -m sixcat --base-url http://127.0.0.1:8085/v1 --model qwen38-27b --out run.json
```

Default is `--limit 20` and `--max-minutes 30`. Each item is appended to `run.jsonl` as it finishes. Crash the box, rerun the same command: it prints `SKIP` for done keys and continues. `--no-resume` starts a new log.

```text
PASS knowledge/mmlu:3 pred=B gold=B
FAIL math/gsm:1 pred=12 gold=29
TIMEUP before instruct/ifeval:1005
```

`--full` is 740 items. It still stops at 30 minutes unless you pass `--max-minutes 0`.

Thinking is forced off via `chat_template_kwargs.enable_thinking=false`. Temperature 0.

## Full vs smoke

| | Items | Typical wall on Quadro RTX 6000 @ ~24 tg |
|---|---:|---|
| default (`--limit 20`) | ~180 | **≤30 min** |
| `--limit 3` | ~47 | a few minutes |
| `--full` | 740 | can exceed 1 hour — not the daily run |

Do not compare a `--limit` smoke to a full row.

## Method

- One stream. One model id. Same prompt template every run.
- Multiple choice: “Reply with only the letter.”
- GSM8K: “End with `#### <number>`.”
- Tools: OpenAI `tools=` on `/v1/chat/completions`.

Unit tests (no GPU):

```bash
python -m unittest discover -s tests -v
```

## What we refuse to mix in

- `llama-bench` tok/s (speed, not quality)
- Hosted API queue time
- ngram / cache-hit decode
- Hermes `-Q` 0-tool scores
- Ada / Blackwell numbers labeled as this box

## License

MIT for the harness. Upstream eval items keep their original licenses (tinyBenchmarks, IFEval, HumanEval).
