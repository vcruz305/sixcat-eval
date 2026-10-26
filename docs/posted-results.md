# Posted SixCat results

Public SixCat scores posted by [Victor (@ViC305)](https://x.com/ViC305), newest first.
Transcribed from the 2026-10-25 extract of those posts. Every figure below is copied
from that extract. This page does not remeasure a run.

The two receipts already in the repo stay in
[README-v0.5.1.md](../README-v0.5.1.md): GLM-5.3-Flash v0.5.0 (overall 91.7) and
Qwen3.8-27B EXL3 4.00bpw v0.5.1 (overall 75.0). See the footnotes for which
posted rows are other runs of those model names.

The archived results table also has weights (HF), transport, and sampling policy.
Those fields were not in these posts, so the columns are omitted here. When a
post folded vendor sampling into the version string, that text stays in the
sixcat cell as posted.

## How to read a cell

- **n/p** means not posted. The extract left the cell blank.
- **—** means unknown. The extract recorded the field as unknown, not readable, or not stated, and gave no value.
- The **sixcat** cell is filled only when the extract names a version. `pre-0.5` is that extract's bound (`pre-0.5 (unknown)`). The exact release was not stated. `v0.5.1 (vendor, thinking on)`, `v0.7.0`, and `v0.4.4 (high-budget rerun)` are copied as written.
- **n** is the posted run size, copied as written. This page does not define the fractions in `120 (101/120)` and `120 (93/120)`.
- **(partial) †** is a 60-item slice. The 2026-08-22 post said there was no honest overall for these two runs. The cell repeats the posted slice figure. It is a partial result.
- **‡** The GLM-5.3 slice (88.3, ZenMux, 60-item slice, 53/60) is a different run from the archived [GLM-5.3-Flash v0.5.0 receipt](../README-v0.5.1.md) (overall 91.7).
- **§** The Qwen3.8-27B board rows (stock Q4 82.3 and AEON Q4+MTP 80.0) are different setups from the archived [Qwen3.8-27B EXL3 4.00bpw v0.5.1 receipt](../README-v0.5.1.md) (overall 75.0).
- **‖** Both 2026-09-09 rows were posted under the name Qwen3.8-Flash-Next. The model cell repeats the posted quant so the category row stays tied to the results row. The precision cell is that same string.
- **¶** The extract listed llama.cpp for the Ornith-1.5 GGUF board row as assumed and not stated. Serving is —.
- Marker symbols are labels, not part of the score.
- Category cells are plain figures. Bold in the archived category table means zero loop failures, zero truncation, and zero empty answers. These posts did not include that diagnostic.

## Results

| date (PT) | model | precision | hardware / serving | sixcat | n | overall | decode tok/s | post |
|---|---|---|---|---|---|---:|---|---|
| 2026-10-17 | Qwen3.8-Flash-Next (FP4-Local, TP1) | FP4-Local | 1x DGX Spark · — | — | — | 90.8 | 68 | [post](https://x.com/ViC305/status/2111523015234384166) |
| 2026-10-16 | Nemotron 3.5 Super VL 120B-A12B | NVFP4 (NVIDIA) | 1x DGX Spark · vLLM 0.31.0 + FlashInfer, MTP-5 | — | 120 (101/120) | 84.17 | 37.3 | [post](https://x.com/ViC305/status/2111165770159845500) |
| 2026-10-16 | Nemotron 3.5 Bolt 74B-A9B (24GB IQ2) | Mixed ModelOpt IQ2 | 1x DGX Spark · vLLM (no draft for quality run) | — | 120 (93/120) | 77.50 | 30.9 (no draft) / 87.8 w/ LiLiCorr DFlash | [post](https://x.com/ViC305/status/2111165770159845500) |
| 2026-10-13 | MiniCPM-V 4.7 35B-A3B | SAGE-EXL3 3.74bpw | 1x DGX Spark · ExLlamaV3 + TabbyAPI | v0.7.0 | — | 79.17 | 69.7 (p50); 125 on REXL3 | [post](https://x.com/ViC305/status/2110095908386042323) |
| 2026-09-09 | Qwen3.8-Flash-Next (EXL3 ~3-bit, MTP on) ‖ | EXL3 ~3-bit (MTP on) | 1x DGX Spark · vLLM + vllm-exl3 | v0.5.1 (vendor, thinking on) | 120 | 86.7 | 47.6 (p50) | [post](https://x.com/ViC305/status/2097723351993385463) |
| 2026-09-09 | Qwen3.8-Flash-Next (GGUF Q4_K_M, BF16 PLE on NVMe, MTP on) ‖ | GGUF Q4_K_M (BF16 PLE on NVMe, MTP on) | 1x DGX Spark · llama.cpp | v0.5.1 (vendor, thinking on) | 120 | 89.2 | 32.9 (p50) | [post](https://x.com/ViC305/status/2097723351993385463) |
| 2026-08-25 | Apodex-1.1-mini | NVFP4 experts, FP8 attn/KV | 1x DGX Spark GB10 · SGLang (flashinfer_cutlass) | v0.4.4 (high-budget rerun) | 120 | 83.3 | 83 | [post](https://x.com/ViC305/status/2092349512044212705) |
| 2026-08-22 | Ox Alpha (via Nous Portal) † | cloud | hosted · Nous Portal API | — | 60-item slice (54/60) | 90.0 (partial) † | n/p | [post](https://x.com/ViC305/status/2091361652776292473) |
| 2026-08-22 | GLM-5.3 (via ZenMux) † ‡ | cloud | hosted · ZenMux API | — | 60-item slice (53/60) | 88.3 (partial) † ‡ | n/p | [post](https://x.com/ViC305/status/2091361652776292473) |
| 2026-08-19 | Ornith-1.5-35B-A3B | NVFP4 (ModelOpt) | 1x DGX Spark · vLLM, single node TP1 | pre-0.5 | — | 85.0 | ~78 (prefill ~3891) | [post](https://x.com/ViC305/status/2090094880882393484) |
| 2026-08-19 | Qwen3.8-27B stock Q4 § | Q4 | — | pre-0.5 | — | 82.3 § | n/p | [post](https://x.com/ViC305/status/2090094880882393484) |
| 2026-08-19 | Ornith-1.5 GGUF Q4_K_M ¶ | GGUF Q4_K_M | Quadro RTX 6000 24GB · — ¶ | pre-0.5 | — | 80.6 | n/p | [post](https://x.com/ViC305/status/2090094880882393484) |
| 2026-08-19 | Qwen3.8-27B AEON Q4+MTP § | Q4 + MTP | — | pre-0.5 | — | 80.0 § | n/p | [post](https://x.com/ViC305/status/2090094880882393484) |
| 2026-08-19 | Nemotron 3.5 Lightning NVFP4 | NVFP4 | — | pre-0.5 | — | 57.9 | n/p | [post](https://x.com/ViC305/status/2090094880882393484) |

## Categories

Same order as the results table. **n/p** was not posted. **—** is the extract's unknown.

| model | knowledge | math | truth | instruct | code | tools |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3.8-Flash-Next (FP4-Local, TP1) | n/p | n/p | n/p | n/p | n/p | n/p |
| Nemotron 3.5 Super VL 120B-A12B | 85 | 100 | 85 | 50 | 100 | 85 |
| Nemotron 3.5 Bolt 74B-A9B (24GB IQ2) | 60 | 100 | 80 | 50 | 85 | 90 |
| MiniCPM-V 4.7 35B-A3B | — | 100 | — | — | 85 | 90 |
| Qwen3.8-Flash-Next (EXL3 ~3-bit, MTP on) ‖ | 85 | 100 | 80 | 85 | 90 | 80 |
| Qwen3.8-Flash-Next (GGUF Q4_K_M, BF16 PLE on NVMe, MTP on) ‖ | 85 | 100 | 85 | 90 | 85 | 90 |
| Apodex-1.1-mini | 65 | 95 | 80 | 90 | 80 | 90 |
| Ox Alpha (via Nous Portal) † | 80 | 100 | 90 | n/p | n/p | n/p |
| GLM-5.3 (via ZenMux) † ‡ | 80 | 100 | 85 | n/p | n/p | n/p |
| Ornith-1.5-35B-A3B | — | 95.0 | — | — | — | 100.0 |
| Qwen3.8-27B stock Q4 § | n/p | n/p | n/p | n/p | n/p | n/p |
| Ornith-1.5 GGUF Q4_K_M ¶ | n/p | n/p | n/p | n/p | n/p | n/p |
| Qwen3.8-27B AEON Q4+MTP § | n/p | n/p | n/p | n/p | n/p | n/p |
| Nemotron 3.5 Lightning NVFP4 | n/p | n/p | n/p | n/p | n/p | n/p |

## Extract notes

- **2026-10-17 · Qwen3.8-Flash-Next (FP4-Local, TP1).** Article post. The category breakdown is in the X Article body, which the API did not return, so those six cells are n/p. A 2-Spark TP2 run was 32% slower decode and has no separate score.
- **2026-10-16 · Nemotron 3.5 Super VL 120B-A12B.** Receipt flagged instruction truncation/looping. 90.9 tok/s balanced @C=8. The decode cell is the posted 37.3.
- **2026-10-16 · Nemotron 3.5 Bolt 74B-A9B (24GB IQ2).** Score from an earlier no-draft quality run. Receipt flagged instruction truncation/looping.
- **2026-10-13 · MiniCPM-V 4.7 35B-A3B.** Math, Tools, and Code were posted (100, 90, 85). Knowledge, Truth, and Instruct were not given; the extract recorded them as unknown (—). The HUD image has no Sixcat numbers. Sixcat version v0.7.0.
- **2026-09-09 · Qwen3.8-Flash-Next, both rows.** The posted scores are 86.7 (EXL3) and 89.2 (GGUF). A mixed retry log that printed 90.0 is not the score used here. The Tools row uses the qwen3_xml parser. Sixcat v0.5.1 (vendor, thinking on), n=120.
- **2026-08-25 · Apodex-1.1-mini.** Also recorded in `vcruz305/Apodex-1.1-mini-NVFP4-DGX-Spark-recipe`, outside this repo. Sixcat v0.4.4 (high-budget rerun).
- **2026-08-22 · Ox Alpha (via Nous Portal). †** Incomplete 60-item slice, 54/60, posted overall 90.0. The post said there was no honest full overall. The same post mentions Instruct 7/8 without identifying which model, so that figure is not entered on this row or the GLM row.
- **2026-08-22 · GLM-5.3 (via ZenMux). † ‡** Incomplete 60-item slice, 53/60, posted overall 88.3. Different run from the archived GLM-5.3-Flash v0.5.0 overall 91.7.
- **2026-08-19 · Ornith-1.5-35B-A3B.** Same run also posted at [2090096658877129002](https://x.com/ViC305/status/2090096658877129002) and [2090096320073916552](https://x.com/ViC305/status/2090096320073916552). Recorded in the Ornith-1.5-35B-A3B-DGX-Spark repo, outside this repo. Math 95.0 and Tools 100.0 were posted; the other categories were unknown.
- **2026-08-19 · Qwen3.8-27B stock Q4. §** Board row only. Overall 82.3. Categories were not posted. Different setup from the archived EXL3 4.00bpw overall 75.0.
- **2026-08-19 · Ornith-1.5 GGUF Q4_K_M. ¶** Board row only. Overall 80.6. Hardware posted as Quadro RTX 6000 24GB. Categories were not posted.
- **2026-08-19 · Qwen3.8-27B AEON Q4+MTP. §** Board row only. Overall 80.0. Categories were not posted. Different setup from the archived EXL3 4.00bpw overall 75.0.
- **2026-08-19 · Nemotron 3.5 Lightning NVFP4.** Board row only. Overall 57.9. Categories were not posted.

The four board rows and the Ornith-1.5-35B-A3B row share one source post, [2090094880882393484](https://x.com/ViC305/status/2090094880882393484).

## Posts checked and left out

These posts came up in the same extract and are not SixCat rows here.

- 2026-10-22 Ornith-1.5-122B SAGE-EXL3 2.58bpw 91.78% (324/353) and Mia EAQv1 4.0bpw 91.50% (323/353): a 9-suite 353-question matched benchmark, not labeled SixCat. [post](https://x.com/ViC305/status/2113306019699011864)
- 2026-10-20 DeepSeek V4.1 Flash 1017 SAGE-EXL3 1.62bpw 94.1% (332/353), JJ 2.8bpw 90.1%, Mia 2.9bpw 88.4%: the same 9-suite benchmark, not SixCat. [post](https://x.com/ViC305/status/2112603778327380088)
- 2026-09-16 reply "91.8% overall" is KLD/token agreement, not SixCat. [post](https://x.com/ViC305/status/2100335434945688013)
- 2026-09-01 DeepSeek-V4-Flash-Vision: a first SixCat run was mentioned and held back for a chat-template fix. No score was posted. [post](https://x.com/ViC305/status/2094780816173977984)
- 2026-08-25 Granite 4.2 30B NVFP4 and 2026-08-28 Qwen3.8-Flash-Next Q6_K: "Sixcat results next", with no score found later.
