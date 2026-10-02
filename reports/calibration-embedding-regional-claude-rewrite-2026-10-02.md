# Embedding Model Calibration Report

- **Scored split:** `test` (provenance: synthetic)
- **Date:** 2026-10-02
- **Task:** `embedding` (Knowledge Base Policy Retrieval)
- **Searched field:** `kb_query` (not the customer message `text`)
- **Execution Environment:** Darwin 27.0.0 (arm64), Python 3.12.12, PyTorch 2.14.0 (host, 8 threads)
  (MPS/CUDA for training if available, CPU for inference benchmarking)

## Artifact Provenance & Hashes

- **Configuration:** `tools/calibrate/configs/embedding_regional_claude_rewrite.yaml` (`6ac5f6ea946e2c77b42cf4de283182745f55e346c22b909a5791e419287304e3`)
- **Data Splits:**
- `packages/retrieval/kb/snippets.jsonl`: `25b9c7a8cba25d9102ae86f826c14ab93ce58bc3ecd92754b4719ad752f9b0ca`
- `data/eval/synthetic/retrieval/queries_regional_claude.jsonl`: `b083021ccf5e7f229b7bc794deff3b2b9605ece2135a70f6e37293586b272fe6`

## Calibration Summary Table

| Candidate Model | Mode | Language | Hit@1 | Hit@3 | Hit@5 | MRR | Cross Hit@1 | Cross Hit@3 | Cross Hit@5 | Cross MRR | p95 CPU (ms) | RAM model+inference Δ (MB) |
|---|---|:---:|---: | ---: | ---:|---:|---: | ---: | ---:|---:|---:|---:|
| `bm25` | zeroshot | es | 0.464 | 0.669 | 0.768 | 0.576 | 0.227 | 0.390 | 0.454 | 0.314 | 0.2 | 0.8 |
| `bm25` | zeroshot | pt | 0.541 | 0.726 | 0.785 | 0.633 | 0.267 | 0.430 | 0.519 | 0.358 | 0.2 | 0.8 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | es | 0.481 | 0.662 | 0.756 | 0.586 | 0.501 | 0.677 | 0.748 | 0.591 | 7.7 | 1155.3 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | pt | 0.504 | 0.659 | 0.733 | 0.595 | 0.511 | 0.674 | 0.756 | 0.598 | 7.7 | 1155.3 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | es | 0.610 | 0.807 | 0.859 | 0.711 | 0.630 | 0.795 | 0.832 | 0.709 | 18.6 | 1791.6 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | pt | 0.578 | 0.770 | 0.859 | 0.688 | 0.585 | 0.741 | 0.793 | 0.662 | 18.6 | 1791.6 |

## Score Floor (0.81)

A question gets an answer when its best same- or cross-language score reaches the
floor, as kb.search does. **Lost** is the share of answerable questions left with no
result; **wrongly answered** is the share of questions the KB does not cover (no gold
snippet) that still get a result. BM25 and hybrid scores are not cosines and are
not listed.

| Candidate Model | Language | Answerable | Lost | Not covered | Wrongly answered |
|---|:---:|---:|---:|---:|---:|
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | es | 405 | 0.970 | 45 | 0.000 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | pt | 135 | 0.978 | 15 | 0.000 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | es | 405 | 0.005 | 45 | 0.178 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | pt | 135 | 0.022 | 15 | 0.267 |

## Evaluation Notes & Decisions

1. **Retrieval Baseline:** Evaluated against `bm25` lexical search.
2. **Dense Retrieval:** Evaluated using bi-encoder SentenceTransformers on CPU;
   `hybrid` fuses BM25 and the dense ranking with reciprocal rank fusion.
3. **Same-language (Hit@k, MRR):** the index is restricted to the query's language.
4. **Cross-language (Cross Hit@k, Cross MRR):** the same query against an index
   restricted to the other languages; gold is the query's topic in those
   languages. `n/a` when the KB snippets carry no `topic_id`.
5. **Latency & Resource Footprint:** Measured strictly on CPU (`device=cpu`).
