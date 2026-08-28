# Harness stdio driver (ZCode, Claude Code, Codex, …)

Sixcat scores **raw completions**. It does not grade the agent. If the cloud model is only reachable *inside* a harness (ZCode Coding Plan with no exportable key), run:

```bash
python -m sixcat --transport stdio --model glm-5.3-flash \
  --policy vendor --policy-family glm-5.x --limit 20 \
  --out results/zcode-flash.json --log results/zcode-flash.jsonl
```

**Stdout** = JSONL requests (one `complete` object per line).  
**Stderr** = PASS/FAIL table.  
**Stdin** = one JSON answer per request.

## Request (sixcat → harness)

```json
{"op":"complete","id":"<hex>","model":"glm-5.3-flash","prompt":"...","max_tokens":8192,"tools":null,"request_params":{"temperature":1.0,"max_tokens":8192}}
```

## Answer (harness → sixcat)

```json
{"id":"<same hex>","text":"A","finish":"stop","usage":{"completion_tokens":8,"prompt_tokens":40}}
```

Optional: `reasoning_content`, `tool_calls`, `usage.reasoning_tokens`.

## Binding

1. Send **only** `prompt` as the user message. No extra system prompt, no repo tools, no “you are a coding assistant.”
2. Return the model’s raw text. **Do not grade.** Sixcat scores IFEval / ARC / HumanEval.
3. HumanEval: return code text; sixcat still executes in its sandbox.
4. `--concurrency 1` only (stdio is strictly sequential).
5. Journal identity includes `transport=stdio` and `base_url=stdio://harness`. It **cannot resume** a llama.cpp / OpenAI HTTP log.
6. Cloud GLM-5.3-Flash may not allow think-off. Do not compare that card to a local GGUF preclose run.

## Direct API (preferred when you have a key)

ZCode’s Coding Plan OpenAI door is not the ZCode app:

```bash
export SIXCAT_API_KEY=...   # never paste into chat
python -m sixcat --base-url https://api.z.ai/api/coding/paas/v4 \
  --model glm-5.3-flash --policy vendor --policy-family glm-5.x --limit 20
```

China: `https://open.bigmodel.cn/api/coding/paas/v4`. General prepaid: `/api/paas/v4`. Do not mix those URLs.
