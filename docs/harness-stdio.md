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

Tool-call answers (Tools category) use the OpenAI shape; arguments stay a JSON string:

```json
{"id":"<same hex>","text":"","finish":"tool_calls","tool_calls":[{"function":{"name":"add","arguments":"{\"a\":19,\"b\":23}"}}]}
```

Abstention items (graded on plain text, no calls): send `text` only and no `tool_calls`.

## Driver requirements (learned the hard way)

1. **Answer every request, including the policy probe.** Before the scored items sixcat
   sends one unscored `complete` probe (`"What is 17 multiplied by 23?..."`) to detect the
   thinking mode. Answer it like any request; it is never graded, but the run aborts if it
   goes unanswered. Its prompt will not match any benchmark item, so a hash-keyed answer
   table needs a probe fallback.
2. **Drain stderr concurrently.** Sixcat streams per-item progress to stderr while
   requests flow on stdout. A driver that reads stdout without a concurrent stderr reader
   will deadlock once the OS pipe buffer fills (a few dozen items). Read stderr in a
   thread or redirect it to a file.
3. **Apply `request_params` to the raw model call.** Temperature, top-p, and seed are how
   the selected sampling policy means anything; a driver that ignores them is benchmarking
   its own defaults, not the policy.
4. **Honor `max_tokens` and report truncation honestly.** When the response is cut off,
   send `"finish":"length"`; sixcat records truncation from it and flags the row.
5. **Windows encodings.** Pipes default to the locale codec (often `cp1252`), and prompts
   contain non-ASCII text (degree signs, CJK). Set `PYTHONIOENCODING=utf-8` for the sixcat
   process (and read/write UTF-8 in the driver) to avoid `UnicodeEncodeError` mid-run.

## Binding

1. Send **only** `prompt` as the user message. No extra system prompt, no repo tools, no “you are a coding assistant.”
2. Return the model’s raw text. **Do not grade.** Sixcat scores IFEval / ARC / HumanEval.
3. HumanEval: return code text; sixcat still executes in its sandbox.
4. `--concurrency 1` only (stdio is strictly sequential).
5. Journal identity includes `transport=stdio` and `base_url=stdio://harness`. It **cannot resume** a llama.cpp / OpenAI HTTP log. `--retry remaining|failed|incomplete` works across stdio runs as long as the new invocation also passes `--transport stdio` (the saved result records `transport`, and `retry-plan` emits it).
6. Cloud GLM-5.3-Flash may not allow think-off. Do not compare that card to a local GGUF preclose run.
7. Context/ETA preflight cannot discover anything over stdio (there is no `/v1/models`); expect the `CTX_*`/`USAGE_*` warnings and pass `--ctx N` if you want a recorded input budget.

## Direct API (preferred when you have a key)

ZCode’s Coding Plan OpenAI door is not the ZCode app:

```bash
export SIXCAT_API_KEY=...   # never paste into chat
python -m sixcat --base-url https://api.z.ai/api/coding/paas/v4 \
  --model glm-5.3-flash --policy vendor --policy-family glm-5.x --limit 20
```

China: `https://open.bigmodel.cn/api/coding/paas/v4`. General prepaid: `/api/paas/v4`. Do not mix those URLs.
