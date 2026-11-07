# Adaptive concurrency and serving-speed benchmark

SixCat 0.7 can measure an already-running inference server before the scored run and select a concurrency level automatically.

```bash
python -m sixcat \
  --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_MODEL \
  --policy strict \
  --auto-concurrency \
  --max-minutes 30 \
  --out results/model.json
```

The default discovery curve tests **1, 2, 4, and 8** in-flight requests with unscored synthetic prompts. It does not send SixCat benchmark questions during calibration. For each level it measures aggregate output throughput, request rate, client-observed TTFT, end-to-end latency, effective prefill/decode rates, and provider/server timings when available.

The default recommendation is the **smallest concurrency that reaches at least 90% of the measured peak aggregate throughput**. This deliberately chooses the throughput knee instead of blindly selecting the largest or absolute-peak concurrency, reducing unnecessary TTFT/KV-cache pressure for tiny marginal gains. The curve counts against the same 30-minute invocation budget.

Customize the search when useful:

```bash
python -m sixcat \
  --model YOUR_MODEL \
  --auto-concurrency \
  --concurrency-candidates 1,2,4,8,16 \
  --calibration-seconds 90 \
  --calibration-knee-fraction 0.90
```

## Speed-only suite: one command, three legitimate workloads

For users who want a real serving-performance receipt without running the quality benchmark, the default command now runs **three intentionally different workloads**:

```bash
python -m sixcat speed \
  --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_MODEL \
  --out results/model-speed.json
```

| Profile | Default workload | What the headline means |
|---|---|---|
| **decode** | ~32 prompt words + up to 512 generated tokens | Sustained **single-stream decode** speed; headline comes from C=1 so batching does not make the model look artificially slow |
| **balanced** | ~256 prompt words + up to 128 generated tokens | Realistic mixed serving throughput, TTFT and the concurrency knee |
| **prefill** | ~2048 prompt words + up to 32 generated tokens | Long-prompt ingestion / effective prefill speed without a long decode tail dominating wall time |

Each profile discovers its **own** concurrency curve with the same workload it later confirms. The curve and confirmation no longer use different output lengths. By default a concurrency level must complete at least **95%** of its requests to participate in knee selection; the report also records the maximum usable concurrency and explicitly marks rejected levels.

The terminal headline separates metrics that answer different questions:

- **Decode:** per-stream p50, p95, max and p90 "best sustained" decode tok/s;
- **Balanced:** aggregate output tok/s at the selected serving knee plus TTFT;
- **Prefill:** single-stream effective prompt-ingestion p50/p95/max;
- **Aggregate output TPS** is labeled as a level-wall metric that includes prefill, queueing and failure wall time; it is not presented as the model's raw decode ceiling.

You can run only one workload when needed:

```bash
python -m sixcat speed --model YOUR_MODEL --profile decode
python -m sixcat speed --model YOUR_MODEL --profile balanced
python -m sixcat speed --model YOUR_MODEL --profile prefill
```

Or define an explicit workload:

```bash
python -m sixcat speed \
  --model YOUR_MODEL \
  --profile custom \
  --prompt-words 64 \
  --max-tokens 1024
```

A fixed `--concurrency N` skips curve discovery; otherwise each profile can choose a different serving knee. `--candidates 1,2,4,8,16`, `--knee-fraction`, and `--min-success-rate` remain available for deeper tuning.

Reported metrics include client TTFT/E2E/TPOT p50/p95/p99, aggregate output tok/s, request rate, effective prefill/decode rates, and native provider/server metrics when available. llama.cpp can expose native prompt/decode timings in its response, while current vLLM can return per-request TTFT, generation/decode time, queue time, mean ITL and output throughput when started with `--enable-per-request-metrics`. When the selected route exposes none of those fields, SixCat prints **"server metrics unavailable for this route"** instead of leaving unexplained nulls.

With fewer than 100 successful confirmation requests, p99 is explicitly marked as a low-sample interpolated tail estimate. Use `--samples 100` or more when p99 is itself an acceptance criterion.

The saved JSON ends with a `summary` object containing the headline raw values plus a ready-to-copy `copy_paste` string, for example:

```text
**Decode:** 81.2 tok/s max, 77.6 tok/s p50
**Prefill:** 1,940.0 tok/s p50
**Balanced serving:** 132.0 tok/s aggregate @ C=4
**TTFT:** 390 ms p50 / 710 ms p95
**Max usable concurrency:** 4
```
