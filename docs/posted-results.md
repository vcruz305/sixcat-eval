# Posted SixCat results

Public SixCat scores posted by [Victor (@ViC305)](https://x.com/ViC305), sorted by overall from highest to lowest.
Partial runs sort by the posted slice percentage and stay marked **partial**.
Transcribed from the v2 extract of those posts, plus the 2026-10-26 Nanbeige4.3-33B row from the owner's Hugging Face model card and recipe.
Every figure is copied from that source. This page does not remeasure a run.

The two receipts already in the repo stay in
[README-v0.5.1.md](../README-v0.5.1.md): GLM-5.3-Flash v0.5.0 (overall 91.7) and
Qwen3.8-27B EXL3 4.00bpw v0.5.1 (overall 75.0). Footnotes ‡ and § name the posted
rows that are other runs of those model names.

The results table includes a weights (HF) column when the extract has a verified link.
Transport is omitted. Sampling policy appears only inside the sixcat cell, and only
as the extract wrote it.

## How to read a cell

- **n/p** means not posted. The extract left that score or speed cell blank.
- **—** means unknown, or no verified value. In the weights column it means there is no verified link.
- **upstream** on a weights link means the repo is not the owner's own quant.
- **own, matched by name** means the owner's repo, matched by name. The post did not link it.
- **own, linked in post** means the owner's repo, and the post linked it.
- **own** on the Nanbeige row means the owner's model card. The X post URL is not in yet.
- The **sixcat** cell copies a version only when the source names one. `pre-0.5` is the extract's bound (`pre-0.5 (unknown)`). The exact release was not stated. `v0.5.1 (vendor, thinking on)`, `v0.7.0`, `v0.4.4 (high-budget rerun)`, and `v0.8.3 (strict, thinking ON)` are copied as written. `— (vendor policy, thinking on)` means the extract did not name a release and did record vendor policy with thinking on.
- **n** is the posted run size, copied as written. This page does not redefine `120 (109/120)`, `120 (104/120)`, `120 (101/120)`, `120 (93/120)`, `119`, or `118/120 eligible`.
- **(partial) †** is a partial result, sorted by its slice percentage. The 2026-08-22 post said there was no honest overall for the Ox Alpha 90.0 and GLM 88.3 slices. The 2026-10-17 2-Spark row is 89.72 on 118/120 and is not a matched comparison.
- **‡** The GLM-5.3 slice (88.3, ZenMux, 60-item slice, 53/60) is a different run from the archived [GLM-5.3-Flash v0.5.0 receipt](../README-v0.5.1.md) (overall 91.7). The weights link is `zai-org/GLM-5.3`. The extract says the exact variant was not stated.
- **§** The Qwen3.8-27B board rows (stock Q4 82.3 and AEON Q4+MTP 80.0) are different setups from the archived [Qwen3.8-27B EXL3 4.00bpw v0.5.1 receipt](../README-v0.5.1.md) (overall 75.0).
- **‖** Both 2026-09-09 rows were posted under the name Qwen3.8-Flash-Next. The model cell repeats the posted quant so the category row stays tied to the results row.
- **¶** The extract listed llama.cpp for the Ornith-1.5 GGUF board row as assumed and not stated. Serving is —. The extract's candidate `ornith-ai/Ornith-1.5-35B-A3B-GGUF` was not verified, so the weights cell is — and that candidate is not linked.
- **◊** Least certain weights link. This is the 2026-09-09 EXL3 row (overall 86.7), the Sep 9 EXL3 ~3-bit row. The revision `3.05bpw_h5_ng5` comes from the owner's [Qwen3.8-Flash-Next-EXL3-DGX-Spark-recipe](https://github.com/vcruz305/Qwen3.8-Flash-Next-EXL3-DGX-Spark-recipe) README. The post did not link it. Serving stays `vLLM + vllm-exl3`, the backend in the extract. That recipe also documents TabbyAPI.
- **ⓐ** Knowledge 90.0, math 100.0, truth 80.0, instruct 95.0, and tools 85.0 are from the owner's repo [Qwen3.8-Flash-Next-FP4-Spark-recipe](https://github.com/vcruz305/Qwen3.8-Flash-Next-FP4-Spark-recipe) README (vendor receipt), not from the X post. Code 95.0 is from the X Article. The extract says the article also confirms overall 90.8.
- **ⓑ** Knowledge 85.0, truth 75.0, instruct 70.0, and code 85.0 are from the owner's repo [Ornith-1.5-35B-A3B-DGX-Spark](https://github.com/vcruz305/Ornith-1.5-35B-A3B-DGX-Spark), file `logs/sixcat-nvfp4-20260819.json`, not from the X post. Math 95.0 and tools 100.0 are from the X image.
- **ⓒ** Knowledge 50, truth 80, and instruct 70 are from the owner's repo [MiniCPM-V-4.7-35B-A3B-EXL3-DGX-Spark-recipe](https://github.com/vcruz305/MiniCPM-V-4.7-35B-A3B-EXL3-DGX-Spark-recipe) README, not from the X post. Math 100, code 85, and tools 90 are from the X post.
- **ⓓ** Nanbeige4.3-33B, overall 86.67, is from the owner's model card [vcruz305/Nanbeige4.3-33B-SAGE-EXL3-4.50bpw](https://huggingface.co/vcruz305/Nanbeige4.3-33B-SAGE-EXL3-4.50bpw) and recipe [Nanbeige4.3-33B-SAGE-EXL3-recipe](https://github.com/vcruz305/Nanbeige4.3-33B-SAGE-EXL3-recipe). The X post is going up 2026-10-26; the post URL will be added later. Two Code completions hit the 32,768-token output cap and are scored failures. This is the first row in the table run on an RTX 4090 rather than a DGX Spark.
- Marker symbols are labels, not part of the score.
- Category cells stay plain figures. Bold in the archived category table means zero loop failures, zero truncation, and zero empty answers. These posts did not include that diagnostic.

## Results

| date (PT) | model | precision | hardware / serving | weights (HF) | sixcat | n | overall | decode tok/s | post |
|---|---|---|---|---|---|---|---:|---|---|
| 2026-10-17 | Qwen3.8-Flash-Next (FP4-Local, TP1) ⓐ | FP4-Local | 1x DGX Spark · b12x vLLM + MTP4 | [nvidia/Qwen3.8-Flash-Next-FP4-Local](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-FP4-Local) · upstream, linked in article | — (vendor policy, thinking on) | 120 (109/120) | 90.8 | 68 | [post](https://x.com/ViC305/status/2111523015234384166) |
| 2026-08-22 | Ox Alpha (via Nous Portal) † | cloud | hosted · Nous Portal API | — | — | 60-item slice (54/60) | 90.0 (partial) † | n/p | [post](https://x.com/ViC305/status/2091361652776292473) |
| 2026-10-17 | Qwen3.8-Flash-Next NVFP4 (NVIDIA) | NVFP4 | 1x DGX Spark · b12x vLLM, base decode | [nvidia/Qwen3.8-Flash-Next-NVFP4](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-NVFP4) · upstream, linked in article | — (vendor policy, thinking on) | 119 | 89.9 | 18.70 | [post](https://x.com/ViC305/status/2111523015234384166) |
| 2026-10-17 | Qwen3.8-Flash-Next FP4-Local TP2 † | FP4-Local | 2x DGX Spark · distributed b12x vLLM | [nvidia/Qwen3.8-Flash-Next-FP4-Local](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-FP4-Local) · upstream, linked in article | — (vendor policy, thinking on) | 118/120 eligible | 89.72 (partial) † | 46.35 | [post](https://x.com/ViC305/status/2111523015234384166) |
| 2026-09-09 | Qwen3.8-Flash-Next (GGUF Q4_K_M, BF16 PLE on NVMe, MTP on) ‖ | GGUF Q4_K_M (BF16 PLE on NVMe, MTP on) | 1x DGX Spark · llama.cpp | [vcruz305/Qwen3.8-Flash-Next-GGUF](https://huggingface.co/vcruz305/Qwen3.8-Flash-Next-GGUF) · own, matched by name | v0.5.1 (vendor, thinking on) | 120 | 89.2 | 32.9 (p50) | [post](https://x.com/ViC305/status/2097723351993385463) |
| 2026-08-22 | GLM-5.3 (via ZenMux) † ‡ | cloud | hosted · ZenMux API | [zai-org/GLM-5.3](https://huggingface.co/zai-org/GLM-5.3) · upstream, variant not stated | — | 60-item slice (53/60) | 88.3 (partial) † ‡ | n/p | [post](https://x.com/ViC305/status/2091361652776292473) |
| 2026-09-09 | Qwen3.8-Flash-Next (EXL3 3.05bpw) ‖ ◊ | EXL3 3.05bpw (turboderp 3.05bpw_h5_ng5 per his recipe) | 1x DGX Spark · vLLM + vllm-exl3 | [turboderp/Qwen3.8-Flash-Next-exl3@3.05bpw_h5_ng5](https://huggingface.co/turboderp/Qwen3.8-Flash-Next-exl3/tree/3.05bpw_h5_ng5) · upstream, least certain ◊ | v0.5.1 (vendor, thinking on) | 120 | 86.7 | 47.6 (p50) | [post](https://x.com/ViC305/status/2097723351993385463) |
| 2026-10-26 | Nanbeige4.3-33B (dense, Llama-arch) ⓓ | SAGE-EXL3 4.50bpw (4.499880554 decoder-body bpw, 8-bit embeddings/head), 18.35 GiB | 1x NVIDIA RTX 4090 (24 GB) · ExLlamaV3 + TabbyAPI, 36,864 ctx, Q4 KV, batch 1 | [vcruz305/Nanbeige4.3-33B-SAGE-EXL3-4.50bpw](https://huggingface.co/vcruz305/Nanbeige4.3-33B-SAGE-EXL3-4.50bpw) · own | v0.8.3 (strict, thinking ON) | 120 (104/120) | 86.67 | 33.82 (token-weighted, 107 requests) | URL later ⓓ |
| 2026-10-17 | Qwen3.8-Flash-Next EXL3 4.05bpw (turboderp) | EXL3 4.05bpw | 1x DGX Spark · ExLlamaV3 + TabbyAPI | [turboderp/Qwen3.8-Flash-Next-exl3@4.05bpw_h6_ng6](https://huggingface.co/turboderp/Qwen3.8-Flash-Next-exl3/tree/4.05bpw_h6_ng6) · upstream, linked in article | — (vendor policy, thinking on) | 119 | 86.5 | 31.97 | [post](https://x.com/ViC305/status/2111523015234384166) |
| 2026-08-19 | Ornith-1.5-35B-A3B ⓑ | NVFP4 (ModelOpt) | 1x DGX Spark · vLLM, single node TP1 | [ornith-ai/Ornith-1.5-35B-A3B-NVFP4](https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B-NVFP4) · upstream, named in post | pre-0.5 | — | 85.0 | ~78 (prefill ~3891) | [post](https://x.com/ViC305/status/2090094880882393484) |
| 2026-10-16 | Nemotron 3.5 Super VL 120B-A12B | NVFP4 (NVIDIA) | 1x DGX Spark · vLLM 0.31.0 + FlashInfer, MTP-5 | [nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4) · upstream, linked in post | — | 120 (101/120) | 84.17 | 37.3 | [post](https://x.com/ViC305/status/2111165770159845500) |
| 2026-08-25 | Apodex-1.1-mini | NVFP4 experts, FP8 attn/KV | 1x DGX Spark GB10 · SGLang (flashinfer_cutlass) | [apodex/Apodex-1.1-mini-NVFP4](https://huggingface.co/apodex/Apodex-1.1-mini-NVFP4) · upstream, linked in post | v0.4.4 (high-budget rerun) | 120 | 83.3 | 83 | [post](https://x.com/ViC305/status/2092349512044212705) |
| 2026-08-19 | Qwen3.8-27B stock Q4 § | Q4 | — | [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) · upstream base, Q4 file not identified | pre-0.5 | — | 82.3 § | n/p | [post](https://x.com/ViC305/status/2090094880882393484) |
| 2026-08-19 | Ornith-1.5 GGUF Q4_K_M ¶ | GGUF Q4_K_M | Quadro RTX 6000 24GB · — ¶ | — | pre-0.5 | — | 80.6 | n/p | [post](https://x.com/ViC305/status/2090094880882393484) |
| 2026-08-19 | Qwen3.8-27B AEON Q4+MTP § | Q4 + MTP | — | [vcruz305/Qwen3.8-27B-AEON-ULTIMATE-UNCENSORED-GGUF](https://huggingface.co/vcruz305/Qwen3.8-27B-AEON-ULTIMATE-UNCENSORED-GGUF) · own, matched by name | pre-0.5 | — | 80.0 § | n/p | [post](https://x.com/ViC305/status/2090094880882393484) |
| 2026-10-13 | MiniCPM-V 4.7 35B-A3B ⓒ | SAGE-EXL3 3.74bpw | 1x DGX Spark · ExLlamaV3 + TabbyAPI | [vcruz305/MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw](https://huggingface.co/vcruz305/MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw) · own, linked in post | v0.7.0 | — | 79.17 | 69.7 (p50); 125 on REXL3 | [post](https://x.com/ViC305/status/2110095908386042323) |
| 2026-10-16 | Nemotron 3.5 Bolt 74B-A9B (24GB IQ2) | Mixed ModelOpt IQ2 | 1x DGX Spark · vLLM (no draft for quality run) | [nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB) · upstream, linked in post | — | 120 (93/120) | 77.50 | 30.9 (no draft) / 87.8 w/ LiLiCorr DFlash | [post](https://x.com/ViC305/status/2111165770159845500) |
| 2026-08-19 | Nemotron 3.5 Lightning NVFP4 | NVFP4 | — | [nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4) · upstream | pre-0.5 | — | 57.9 | n/p | [post](https://x.com/ViC305/status/2090094880882393484) |

## Categories

Same order as the results table. A letter on a score means that figure is from the owner's repo, and the legend names the file. **n/p** was not posted.

| model | knowledge | math | truth | instruct | code | tools |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3.8-Flash-Next (FP4-Local, TP1) ⓐ | 90.0 ⓐ | 100.0 ⓐ | 80.0 ⓐ | 95.0 ⓐ | 95.0 | 85.0 ⓐ |
| Ox Alpha (via Nous Portal) † | 80 | 100 | 90 | n/p | n/p | n/p |
| Qwen3.8-Flash-Next NVFP4 (NVIDIA) | n/p | n/p | n/p | n/p | n/p | n/p |
| Qwen3.8-Flash-Next FP4-Local TP2 † | n/p | n/p | n/p | n/p | n/p | n/p |
| Qwen3.8-Flash-Next (GGUF Q4_K_M, BF16 PLE on NVMe, MTP on) ‖ | 85 | 100 | 85 | 90 | 85 | 90 |
| GLM-5.3 (via ZenMux) † ‡ | 80 | 100 | 85 | n/p | n/p | n/p |
| Qwen3.8-Flash-Next (EXL3 3.05bpw) ‖ ◊ | 85 | 100 | 80 | 85 | 90 | 80 |
| Nanbeige4.3-33B (dense, Llama-arch) ⓓ | 65 | 100 | 85 | 95 | 85 | 90 |
| Qwen3.8-Flash-Next EXL3 4.05bpw (turboderp) | n/p | n/p | n/p | n/p | 100 | n/p |
| Ornith-1.5-35B-A3B ⓑ | 85.0 ⓑ | 95.0 | 75.0 ⓑ | 70.0 ⓑ | 85.0 ⓑ | 100.0 |
| Nemotron 3.5 Super VL 120B-A12B | 85 | 100 | 85 | 50 | 100 | 85 |
| Apodex-1.1-mini | 65 | 95 | 80 | 90 | 80 | 90 |
| Qwen3.8-27B stock Q4 § | n/p | n/p | n/p | n/p | n/p | n/p |
| Ornith-1.5 GGUF Q4_K_M ¶ | n/p | n/p | n/p | n/p | n/p | n/p |
| Qwen3.8-27B AEON Q4+MTP § | n/p | n/p | n/p | n/p | n/p | n/p |
| MiniCPM-V 4.7 35B-A3B ⓒ | 50 ⓒ | 100 | 80 ⓒ | 70 ⓒ | 85 | 90 |
| Nemotron 3.5 Bolt 74B-A9B (24GB IQ2) | 60 | 100 | 80 | 50 | 85 | 90 |
| Nemotron 3.5 Lightning NVFP4 | n/p | n/p | n/p | n/p | n/p | n/p |

## Extract notes

- **2026-10-17 · Qwen3.8-Flash-Next (FP4-Local, TP1). ⓐ** Overall 90.8. n is `120 (109/120)`. Categories: see ⓐ. Weights are the upstream NVIDIA FP4-Local repo, linked in the article.
- **2026-08-22 · Ox Alpha (via Nous Portal). †** Incomplete 60-item slice, 54/60, posted overall 90.0. The post said there was no honest full overall. Sorted by slice percentage 90.0. Instruct 7/8 is mentioned in the post without identifying the model, so that figure is not entered here or on the GLM row. No HF repo (hosted via Nous Portal).
- **2026-10-17 · Qwen3.8-Flash-Next NVFP4 (NVIDIA).** New row from the X Article. Overall 89.9. n is 119 (the extract says a defective MMLU item). Categories were not posted. Decode 18.70. Weights are the upstream NVIDIA NVFP4 repo, linked in the article.
- **2026-10-17 · Qwen3.8-Flash-Next FP4-Local TP2. †** New row from the X Article. Partial, 118/120, overall 89.72, not a matched comparison. Categories were not posted. Decode 46.35. Same upstream FP4-Local repo as the TP1 row.
- **2026-09-09 · Qwen3.8-Flash-Next GGUF.** Overall 89.2, n=120, sixcat `v0.5.1 (vendor, thinking on)`. Categories are from the X post. Weights are the owner's `vcruz305/Qwen3.8-Flash-Next-GGUF`, matched to his Q4_K_M ladder with MTP and BF16 PLE. The post did not link that repo.
- **2026-08-22 · GLM-5.3 (via ZenMux). † ‡** Incomplete 60-item slice, 53/60, posted overall 88.3. Sorted by slice percentage 88.3. Different run from the archived GLM-5.3-Flash v0.5.0 overall 91.7. Weights link is upstream `zai-org/GLM-5.3`; the exact variant was not stated.
- **2026-09-09 · Qwen3.8-Flash-Next EXL3 3.05bpw. ‖ ◊** Overall 86.7. A mixed retry log that printed 90.0 is not the score used here. The Tools row uses the qwen3_xml parser. Categories are from the X post. Serving stays `vLLM + vllm-exl3`. See ◊ for the weights link and the recipe's TabbyAPI note.
- **2026-10-26 · Nanbeige4.3-33B (dense, Llama-arch). ⓓ** Overall 86.67. n is `120 (104/120)`. Sixcat `v0.8.3 (strict, thinking ON)`. Knowledge 65, math 100, truth 85, instruct 95, code 85, tools 90. Decode 33.82 tok/s, token-weighted, 107 requests. Weights are the owner's [vcruz305/Nanbeige4.3-33B-SAGE-EXL3-4.50bpw](https://huggingface.co/vcruz305/Nanbeige4.3-33B-SAGE-EXL3-4.50bpw). Recipe: [Nanbeige4.3-33B-SAGE-EXL3-recipe](https://github.com/vcruz305/Nanbeige4.3-33B-SAGE-EXL3-recipe). The X post is going up 2026-10-26; the post URL will be added later. See ⓓ.
- **2026-10-17 · Qwen3.8-Flash-Next EXL3 4.05bpw (turboderp).** New row from the X Article. Overall 86.5. n is 119. Code is 100. The other categories were not posted. Decode 31.97. Serving is ExLlamaV3 + TabbyAPI. Weights are the upstream turboderp revision `4.05bpw_h6_ng6`, linked in the article.
- **2026-08-19 · Ornith-1.5-35B-A3B. ⓑ** Overall 85.0. Same run also posted at [2090096658877129002](https://x.com/ViC305/status/2090096658877129002) and [2090096320073916552](https://x.com/ViC305/status/2090096320073916552). See ⓑ for which categories come from `logs/sixcat-nvfp4-20260819.json`. Weights are upstream `ornith-ai/Ornith-1.5-35B-A3B-NVFP4`, named in the post image and in that repo.
- **2026-10-16 · Nemotron 3.5 Super VL 120B-A12B.** Receipt flagged instruction truncation/looping. 90.9 tok/s balanced @C=8. The decode cell is the posted 37.3. Categories are from the X post. Weights are the upstream NVIDIA NVFP4 repo, linked in the post.
- **2026-08-25 · Apodex-1.1-mini.** Also recorded in `vcruz305/Apodex-1.1-mini-NVFP4-DGX-Spark-recipe`, outside this repo. Sixcat v0.4.4 (high-budget rerun). Categories are from the X post and image. Weights are upstream `apodex/Apodex-1.1-mini-NVFP4`, linked in the post. The owner's GGUF `vcruz305/Apodex-1.1-mini-GGUF` was also linked and is not the scored file.
- **2026-08-19 · Qwen3.8-27B stock Q4. §** Board row only. Overall 82.3. Categories were not posted. Different setup from the archived EXL3 4.00bpw overall 75.0. Weights link is the upstream base `Qwen/Qwen3.8-27B`. The exact Q4 file was not identifiable.
- **2026-08-19 · Ornith-1.5 GGUF Q4_K_M. ¶** Board row only. Overall 80.6. Hardware is Quadro RTX 6000 24GB. Categories were not posted. See ¶.
- **2026-08-19 · Qwen3.8-27B AEON Q4+MTP. §** Board row only. Overall 80.0. Precision stays `Q4 + MTP`, as posted. Categories were not posted. Different setup from the archived EXL3 4.00bpw overall 75.0. Weights are the owner's `vcruz305/Qwen3.8-27B-AEON-ULTIMATE-UNCENSORED-GGUF`, matched by name (AEON, Q4_K_M, MTP baked in). The post did not link that repo.
- **2026-10-13 · MiniCPM-V 4.7 35B-A3B. ⓒ** Overall 79.17. Sixcat v0.7.0. The X post has math, tools, and code. Knowledge, truth, and instruct are from the recipe README; see ⓒ. The HUD image has no Sixcat numbers. Weights are the owner's `vcruz305/MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw`, linked in the post.
- **2026-10-16 · Nemotron 3.5 Bolt 74B-A9B (24GB IQ2).** Score from an earlier no-draft quality run. Receipt flagged instruction truncation/looping. Categories are from the X post. Weights are the upstream NVIDIA 24GB repo, linked in the post.
- **2026-08-19 · Nemotron 3.5 Lightning NVFP4.** Board row only. Overall 57.9. Categories were not posted. Weights are upstream `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`.

The four Aug 19 board rows and the Ornith-1.5-35B-A3B row share one source post, [2090094880882393484](https://x.com/ViC305/status/2090094880882393484). The four 2026-10-17 rows share [2111523015234384166](https://x.com/ViC305/status/2111523015234384166).

## Posts checked and left out

These are not rows in the tables above.

- Aug 19 SGLang 87.08 was not added. It was not posted.
- 2026-10-22 Ornith-1.5-122B SAGE-EXL3 2.58bpw 91.78% (324/353) and Mia EAQv1 4.0bpw 91.50% (323/353): a 9-suite 353-question matched benchmark, not labeled SixCat. [post](https://x.com/ViC305/status/2113306019699011864)
- 2026-10-20 DeepSeek V4.1 Flash 1017 SAGE-EXL3 1.62bpw 94.1% (332/353), JJ 2.8bpw 90.1%, Mia 2.9bpw 88.4%: the same 9-suite benchmark, not SixCat. [post](https://x.com/ViC305/status/2112603778327380088)
- 2026-09-16 reply "91.8% overall" is KLD/token agreement, not SixCat. [post](https://x.com/ViC305/status/2100335434945688013)
- 2026-09-01 DeepSeek-V4-Flash-Vision: a first SixCat run was mentioned and held back for a chat-template fix. No score was posted. [post](https://x.com/ViC305/status/2094780816173977984)
- 2026-08-25 Granite 4.2 30B NVFP4 and 2026-08-28 Qwen3.8-Flash-Next Q6_K: "Sixcat results next", with no score found later.
