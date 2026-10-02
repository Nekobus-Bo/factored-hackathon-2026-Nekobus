# Plan: compare MiniLM and four candidate embedding models for `kb.search`

## Context

`kb.search` runs on `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, a paraphrase model rather than a retrieval model ([docs/embeddings.md](../../docs/embeddings.md)). [docs/embedding-model-candidates.md](../../docs/embedding-model-candidates.md) chose four candidates from public benchmarks, but none has been scored on our knowledge base. This lab step measures all five on the same data the calibration harness uses, **before** anything changes in `packages/retrieval`, the harness configs or the `.env` pins. It answers two questions:

1. Is any candidate worth a `make calibrate TASK=embedding` run and an ADR-0006 amendment?
2. Is the query/passage prefix option, which e5-small and Harrier need, worth building in the adapters?

Notebook: [compare__kb-embeddings.py](compare__kb-embeddings.py) (`make lab NB=compare__kb-embeddings.py`). Run on 2026-10-01, Apple Silicon CPU, 4 torch threads, sentence-transformers 6.1.0, transformers 5.17.0.

### What a winner must meet

From the candidates doc:

| Requirement | Why |
|---|---|
| Multilingual es/pt/en, including cross-language matching | `kb.search` falls back to the other languages (CROSS) |
| Fits the CPU encoder | 3 GB limit shared with the DistilBERT decision model (446 MiB), ADR-0008 |
| Loads with sentence-transformers, no `trust_remote_code` | Keeps the revision and hash pins meaningful |
| Open weights, commercial license, no gated download | `make warmup-retrieval` and the Cloud Run build download without login |
| Beats MiniLM in our harness | Same-language Hit@1 0.494, cross-language Hit@1 0.508 |

## Finding outside the comparison: the MiniLM pin is broken under transformers v5

The notebook's sanity check failed on the first run: MiniLM at the revision pinned in `.env.example` (`86741b4e3f5c`) scored **Hit@1 0.050**, about chance (1/40), against the report's 0.494.

- The weights at that revision are byte-identical to `main` (`model.safetensors` sha256 `eaa086f0ffee…`, the value of `EMBEDDING_WEIGHTS_SHA256`). Only `tokenizer_config.json` differs.
- Upstream fixed it in `e8f8c211226b` (2026-01-28): "Set tokenizer_class to PreTrainedTokenizerFast for transformers v5 compat".
- Under transformers 5.x, `86741b4e` loads a `BertTokenizer` that turns most words into `<unk>`: `"quiero bloquear mi tarjeta"` → `['<unk>', '<unk>', 'mi', '<unk>']`. `e8f8c211` gives `['▁quiero', '▁bloque', 'ar', '▁mi', '▁tarjeta']`.
- The repo locks transformers 5.16.1, and `86741b4e` is pinned in `.env.example`, `infra/compose/docker-compose.yml` and `infra/deploy/gcp/variables.tf`. **`kb.search` is therefore very likely serving near-random rankings today.** The 2026-09-27 report used `main` (its config sets no revision), so it measured the fixed tokenizer, not what is deployed.
- **Not verified here:** the running encoder container. Check it there before changing anything.
- **Fix, independent of any model switch:** move `EMBEDDING_REVISION` to `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` (the weights hash stays the same), update the tests that hard-code the old pin, `make warmup-retrieval`, and record it in `docs/limitations.md` and an ADR-0006 amendment.

The notebook keeps both: `minilm` (the fixed revision, the baseline, which reproduces the report exactly) and `minilm@env-pin` (what is deployed).

## Models

| Row in the notebook | Model | Pinned revision |
|---|---|---|
| `minilm` (baseline) | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | `e8f8c211226b` (tokenizer fix) |
| `minilm@env-pin` | same | `86741b4e3f5c` (as `.env.example`) |
| `e5-small`, `e5-small+prefix` | `intfloat/multilingual-e5-small` | `614241f622f5` |
| `granite-97m` | `ibm-granite/granite-embedding-97m-multilingual-r2` | `835ad14087e1` |
| `granite-311m` | `ibm-granite/granite-embedding-311m-multilingual-r2` | `443995599303` |
| `harrier`, `harrier+instruction` | `microsoft/harrier-oss-v1-270m` | `31de22b67391` |

e5-small and Harrier run **with and without** their prefixes, so the value of the prefix option is measured, not assumed. e5 uses `query: ` / `passage: `. Harrier uses a domain instruction on queries only (`Instruct: Given a bank customer's question, retrieve the policy passage that answers it\nQuery: `), as its card recommends. Both pool with `include_prompt: true`, so gluing the prefix onto the text, as an adapter would, gives the same vectors as `encode(prompt=...)`. Granite ships empty prompts and needs none.

## Results

Pooled over the 360 validation queries (equal to the mean of es/pt/en). Δ is the paired bootstrap 95% CI against `minilm` (2,000 resamples). Latency is one query at a time, encode + ranking. Weights are parameters × bytes as loaded, not process RSS.

| Model | Hit@1 | Hit@5 | MRR | Cross Hit@1 | Cross MRR | Hit@1 Δ (95% CI) | Cross Hit@1 Δ (95% CI) | p50 / p95 ms | Weights MB | dtype | dims |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---|---:|
| bm25 (report) | 0.366 | 0.603 | 0.456 | 0.144 | 0.197 | | | — / 0.2 | — | | |
| **minilm** (baseline) | 0.494 | 0.794 | 0.605 | 0.508 | 0.593 | — | — | 5.2 / 5.9 | 449 | fp32 | 384 |
| minilm@env-pin | 0.050 | 0.189 | 0.094 | 0.036 | 0.077 | −0.444 [−0.497, −0.389] | −0.472 [−0.525, −0.417] | 5.1 / 6.0 | 449 | fp32 | 384 |
| e5-small | 0.622 | 0.889 | 0.729 | 0.550 | 0.664 | +0.128 [+0.072, +0.181] | +0.042 [−0.011, +0.092] | 5.5 / 7.7 | 449 | fp32 | 384 |
| e5-small+prefix | 0.644 | 0.889 | 0.745 | 0.594 | 0.699 | +0.150 [+0.097, +0.203] | +0.086 [+0.033, +0.142] | 5.1 / 6.2 | 449 | fp32 | 384 |
| granite-97m | 0.614 | 0.889 | 0.727 | 0.600 | 0.708 | +0.119 [+0.061, +0.175] | +0.092 [+0.036, +0.147] | 11.6 / 37.0* | 186 | bf16 | 384 |
| **granite-311m** | **0.714** | **0.967** | **0.820** | **0.703** | **0.792** | **+0.219 [+0.167, +0.275]** | **+0.194 [+0.144, +0.244]** | 30.1 / 36.5 | 594 | bf16 | 768 |
| harrier | 0.658 | 0.919 | 0.767 | 0.619 | 0.731 | +0.164 [+0.114, +0.214] | +0.111 [+0.058, +0.161] | 31.8 / 38.2 | 511 | bf16 | 640 |
| harrier+instruction | 0.667 | 0.933 | 0.771 | 0.628 | 0.735 | +0.172 [+0.119, +0.225] | +0.119 [+0.067, +0.172] | 62.1 / 67.8 | 511 | bf16 | 640 |

\* granite-97m's p95 was 11.9 ms in a first run and 37.0 ms in the second: a noisy tail on a shared laptop. Its p50 (10–12 ms) is the steadier figure.

Per language, same-language Hit@1 (es / pt / en): minilm 0.492 / 0.458 / 0.533 · granite-311m 0.650 / 0.758 / 0.733 · harrier 0.658 / 0.675 / 0.642 · granite-97m 0.592 / 0.642 / 0.608 · e5-small+prefix 0.617 / 0.683 / 0.633. Spanish is the weakest language for every candidate.

### What the results say

- **Every candidate beats MiniLM** on same-language Hit@1, and every bootstrap CI excludes 0. MTEB's ordering mostly holds on our data.
- **granite-311m wins clearly:** +0.22 same-language and +0.19 cross-language Hit@1, Hit@5 0.967, and its CI does not overlap e5's or granite-97m's. It needs no prompts.
- **The prefix option is not worth building now.** Harrier's instruction adds +0.009 Hit@1 (noise) and doubles latency, because the instruction is longer than the query. e5's prefixes add +0.022 same and +0.044 cross, also within noise, and e5 trails granite-311m either way.
- **Cost is acceptable for all of them:** the slowest useful row is about 37 ms p95, small next to LLM latency. granite-311m's 594 MB of bf16 weights plus DistilBERT's 446 MiB stays well under the 3 GB encoder limit, but runtime RSS on Linux is still unmeasured.

## Pros and cons

From desk research (model cards, MTEB, the Granite R2 paper) unless marked **measured**.

### MiniLM-L12-v2 (current)

**Pros**
- Already served: no migration cost beyond fixing the revision pin.
- Fastest with e5: **measured** p95 about 6 ms.
- 384 dimensions, no prompts, about 118M parameters; Apache 2.0.

**Cons**
- **Measured:** the deployed pin (`86741b4e`) is broken under transformers v5 (Hit@1 0.050); see the finding above.
- **Measured:** last of the five even with the fixed tokenizer: Hit@1 0.494 against 0.61–0.71 for the candidates. It was trained for paraphrase, not retrieval (26.1 on the Granite paper's 5-benchmark average, the lowest of 14).
- 128-token limit can truncate the longer snippets.
- **Measured:** fp32, 449 MB of weights for its size class.

### multilingual-e5-small

**Pros**
- **Measured:** as fast as MiniLM (p95 about 6 ms) with Hit@1 0.62–0.64, so the cheapest real gain.
- 384 dimensions: the index shape does not change. 512 tokens covers every snippet. MIT.

**Cons**
- **Measured:** cross-language without prefixes is not clearly better than MiniLM (CI −0.011 to +0.092).
- Needs `query: ` / `passage: ` for its best result: a prefix option in the adapters and the harness. **Measured:** that option is worth +0.02 to +0.04, within noise.
- **Measured:** fp32, 449 MB: no memory gain over MiniLM.
- **Measured:** clearly behind granite-311m on every quality metric.

### granite-embedding-97m-multilingual-r2

**Pros**
- Configuration-only switch: no prompts, 384 dimensions, so the index shape is unchanged.
- **Measured:** smallest memory, 186 MB (loads as bf16 by default; the desk worry that it would load as fp32 is contradicted).
- **Measured:** best cross-language of the 384-dimension models (0.600) and +0.12 same-language over MiniLM.
- Apache 2.0.

**Cons**
- **Measured:** about 2× MiniLM's latency (p50 10–12 ms), with a noisy p95 tail on this machine.
- **Measured:** same-language Hit@1 (0.614) is no better than e5-small and below Harrier and granite-311m.
- 32k-token context adds nothing for our snippets.

### granite-embedding-311m-multilingual-r2

**Pros**
- **Measured:** best on every quality metric: Hit@1 0.714, MRR 0.820, Hit@5 0.967, cross Hit@1 0.703. Its gain over MiniLM is the only one large enough to stand out from every other candidate.
- Configuration-only switch: no prompts.
- **Measured:** loads as bf16 (594 MB), comfortably within the encoder budget next to DistilBERT.
- Matryoshka: vectors can be cut from 768 to 384 dimensions if index size matters (not tested here). Apache 2.0.

**Cons**
- **Measured:** about 6× MiniLM's latency (p95 36.5 ms). Fine against LLM latency, but the highest of the configuration-only options.
- 768 dimensions: harmless in memory, matters for a future pgvector column.
- **Measured:** the largest weights of the five; runtime RSS on the Linux encoder still needs measuring.

### harrier-oss-v1-270m

**Pros**
- **Measured:** second-best quality (Hit@1 0.658 without an instruction), and the best Spanish Hit@1 with the instruction (0.675).
- Works without the instruction: no adapter change needed for 0.658.
- No `trust_remote_code`; MIT.

**Cons**
- **Measured:** the instruction doubles latency (p95 38 → 68 ms) for +0.009 Hit@1, within noise.
- **Measured:** p95 about 38 ms, like granite-311m, but lower quality.
- Decoder (Gemma 3) with last-token pooling: the least familiar architecture in our stack, and 640 dimensions.
- **Measured:** bf16, 511 MB.

## What the notebook measures

It matches the harness (`tools/calibrate/src/calibrate/runner.py`, `metrics/retrieval.py`) so the numbers are comparable with [the committed report](../../reports/calibration-embedding-2026-09-27.md). The `minilm` row reproduces that report's per-language Hit@1 and MRR exactly.

- **Data:** the 120 KB snippets and the 360 `validation` queries the harness uses (`embedding_kb_v1.yaml`).
- **Indexed text:** `f"{title} {text}"`, unit-normalized vectors, cosine as a dot product (`SentenceTransformersAdapter`).
- **Same-language:** only the query's language is ranked; gold is `relevant_ids`.
- **Cross-language:** only the other two languages are ranked; gold is the query's topic in those languages (`KnowledgeBase.cross_language_gold`).
- **Hit@1/3/5 and MRR**, with the ranking cut at 5 before MRR, as the harness does.
- **Cost:** load time, dtype actually loaded, dimensions, p50/p95 latency for one query at a time (4 CPU threads), weights in memory.
- **Sanity check:** MiniLM must reproduce the report within 0.01, or nothing else in the notebook is trusted.
- **Paired bootstrap** against MiniLM, a prefix-effect table, and a misses table per model.

## Decision rule

A candidate moves on to the harness only if all of these hold:

1. Its same-language Hit@1 beats MiniLM's, and the paired bootstrap CI excludes 0.
2. Its cross-language Hit@1 CI does not sit entirely below 0.
3. Its weights fit next to DistilBERT under the encoder's 3 GB limit with margin, and Linux RSS confirms it.
4. Its p95 latency stays small next to LLM latency (tens of ms, not hundreds).

Among the models that pass, prefer one that needs no prefixes before the freeze.

**Outcome:** granite-311m passes 1, 2 and 4; 3 passes on weights and still needs the Linux RSS figure. granite-97m is the lighter fallback (passes all four, 186 MB). The prefix option is not justified by these numbers.

**Adopted on 2026-10-01:** granite-311m, loaded in fp32, replaced MiniLM ([ADR-0006](../../docs/adr/0006-single-postgres-pgvector.md), amendment 2026-10-01). The harness confirmed it in fp32 (Hit@1 0.719, cross 0.711, `reports/calibration-embedding-2026-10-02.md`). The score floor moved to 0.80 (`reports/embedding-score-floor-2026-10-02.md`). The compose encoder measured 2.08 GiB of 3 GiB with Granite and DistilBERT. The steps below are kept as the plan that led there.

## Next steps

1. **First, separately: fix the MiniLM pin** (see the finding above). It is a bug fix, not a model change, and it holds whatever happens with the candidates.
2. Copy `embedding_kb_v1.yaml` with `granite-embedding-311m-multilingual-r2` and `granite-embedding-97m-multilingual-r2` as `sentence_transformers` candidates, run `make calibrate TASK=embedding CONFIG=<new config>`, and commit the report to `reports/`. The harness passes no revision, so note the revisions above in the report.
3. Measure granite-311m's RSS and p95 inside the Linux encoder container (`make encoder-bench` or equivalent).
4. If it holds: an ADR-0006 amendment; `EMBEDDING_MODEL`, `EMBEDDING_REVISION`, `EMBEDDING_WEIGHTS_SHA256` in `.env.example` and `infra/deploy/gcp/variables.tf`; `make warmup-retrieval`; update `docs/embeddings.md`, `docs/embedding-model-candidates.md` and `docs/limitations.md`. Recalibrate `RETRIEVAL_SCORE_FLOOR` (0.3), since the new model's score distribution will differ.
5. Every number here comes from synthetic queries; a human-written test set (even 30 queries per language) remains the real check.
