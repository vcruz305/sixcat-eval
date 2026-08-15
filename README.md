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
4. **[Full vs smoke](#full-vs-smoke)** — item counts and wall time.
5. **[What we refuse to mix in](#what-we-refuse-to-mix-in)**

**Jump to:** [Install](#quick-start) · [Categories](#categories) · [Method](#method)

## Score contract

| Category | Source | Full n | Metric |
|---|---|---:|---|
| Knowledge | tinyMMLU + tinyARC + tinyHellaSwag + tinyWinogrande | 400 | letter match |
| Math | tinyGSM8K | 100 | `####` number match |
| Truth | tinyTruthfulQA (mc1) | 100 | letter match |
| Instruct | IFEval first 100 prompts | 100 | all listed constraints pass |
| Code | HumanEval first 20 | 20 | `pass@1` via local exec |
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

# server must already be up
python -m sixcat --base-url http://127.0.0.1:8085/v1 --model qwen38-27b --limit 3 --out smoke.json
```

Full battery (omit `--limit`):

```bash
python -m sixcat --base-url http://127.0.0.1:8085/v1 --model qwen38-27b --out full.json
```

`--limit N` caps **each dataset** (knowledge has four datasets, so knowledge n = 4N).

Thinking is forced off via `chat_template_kwargs.enable_thinking=false`. Temperature 0.

## Full vs smoke

| | Items | Typical wall on Quadro RTX 6000 @ ~24 tg |
|---|---:|---|
| `--limit 3` | ~47 | a few minutes |
| full | 740 | ~30–45 min |

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
