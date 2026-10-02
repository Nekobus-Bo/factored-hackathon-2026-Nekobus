# Embedding Model Calibration Report

- **Scored split:** `test` (provenance: synthetic)
- **Date:** 2026-10-02
- **Task:** `embedding` (Knowledge Base Policy Retrieval)
- **Execution Environment:** Darwin 27.0.0 (arm64), Python 3.12.12, PyTorch 2.14.0 (host, 8 threads)
  (MPS/CUDA for training if available, CPU for inference benchmarking)

## Artifact Provenance & Hashes

- **Configuration:** `tools/calibrate/configs/embedding_regional_claude_message.yaml` (`0e5252937bc6484d6a22258ceb500e784ccb53ae6dfc16ce306597e6e82d1802`)
- **Data Splits:**
- `packages/retrieval/kb/snippets.jsonl`: `25b9c7a8cba25d9102ae86f826c14ab93ce58bc3ecd92754b4719ad752f9b0ca`
- `data/eval/synthetic/retrieval/queries_regional_claude.jsonl`: `b083021ccf5e7f229b7bc794deff3b2b9605ece2135a70f6e37293586b272fe6`

## Calibration Summary Table

| Candidate Model | Mode | Language | Hit@1 | Hit@3 | Hit@5 | MRR | Cross Hit@1 | Cross Hit@3 | Cross Hit@5 | Cross MRR | p95 CPU (ms) | RAM model+inference Δ (MB) |
|---|---|:---:|---: | ---: | ---:|---:|---: | ---: | ---:|---:|---:|---:|
| `bm25` | zeroshot | es | 0.254 | 0.383 | 0.477 | 0.332 | 0.106 | 0.198 | 0.274 | 0.163 | 0.3 | 0.9 |
| `bm25` | zeroshot | pt | 0.289 | 0.481 | 0.556 | 0.389 | 0.148 | 0.230 | 0.296 | 0.197 | 0.3 | 0.9 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | es | 0.336 | 0.526 | 0.622 | 0.440 | 0.304 | 0.496 | 0.595 | 0.411 | 8.4 | 1168.2 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | pt | 0.311 | 0.504 | 0.630 | 0.421 | 0.356 | 0.519 | 0.622 | 0.454 | 8.4 | 1168.2 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | es | 0.543 | 0.719 | 0.805 | 0.642 | 0.519 | 0.696 | 0.751 | 0.607 | 28.2 | 1791.3 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | pt | 0.533 | 0.756 | 0.830 | 0.651 | 0.570 | 0.726 | 0.763 | 0.641 | 28.2 | 1791.3 |

## Score Floor (0.81)

A question gets an answer when its best same- or cross-language score reaches the
floor, as kb.search does. **Lost** is the share of answerable questions left with no
result; **wrongly answered** is the share of questions the KB does not cover (no gold
snippet) that still get a result. BM25 and hybrid scores are not cosines and are
not listed.

| Candidate Model | Language | Answerable | Lost | Not covered | Wrongly answered |
|---|:---:|---:|---:|---:|---:|
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | es | 405 | 1.000 | 45 | 0.000 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | pt | 135 | 1.000 | 15 | 0.000 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | es | 405 | 0.017 | 45 | 0.089 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | pt | 135 | 0.015 | 15 | 0.133 |

## Evaluation Notes & Decisions

1. **Retrieval Baseline:** Evaluated against `bm25` lexical search.
2. **Dense Retrieval:** Evaluated using bi-encoder SentenceTransformers on CPU;
   `hybrid` fuses BM25 and the dense ranking with reciprocal rank fusion.
3. **Same-language (Hit@k, MRR):** the index is restricted to the query's language.
4. **Cross-language (Cross Hit@k, Cross MRR):** the same query against an index
   restricted to the other languages; gold is the query's topic in those
   languages. `n/a` when the KB snippets carry no `topic_id`.
5. **Latency & Resource Footprint:** Measured strictly on CPU (`device=cpu`).
