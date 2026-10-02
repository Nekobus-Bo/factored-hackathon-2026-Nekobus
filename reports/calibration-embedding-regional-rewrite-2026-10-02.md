# Embedding Model Calibration Report

- **Scored split:** `test` (provenance: synthetic)
- **Date:** 2026-10-02
- **Task:** `embedding` (Knowledge Base Policy Retrieval)
- **Searched field:** `kb_query` (not the customer message `text`)
- **Execution Environment:** Darwin 27.0.0 (arm64), Python 3.12.12, PyTorch 2.14.0 (host, 8 threads)
  (MPS/CUDA for training if available, CPU for inference benchmarking)

## Artifact Provenance & Hashes

- **Configuration:** `tools/calibrate/configs/embedding_regional_rewrite.yaml` (`a308c7903a68ffa3afd53bb1fa731fe0d1c0c4377c071314f85ef58af2054e33`)
- **Data Splits:**
- `packages/retrieval/kb/snippets.jsonl`: `25b9c7a8cba25d9102ae86f826c14ab93ce58bc3ecd92754b4719ad752f9b0ca`
- `data/eval/synthetic/retrieval/queries_regional.jsonl`: `8e2ca09878423186b3ed2d1c9623054a0457ce98585b01cc49c79de9e9f5e7a7`

## Calibration Summary Table

| Candidate Model | Mode | Language | Hit@1 | Hit@3 | Hit@5 | MRR | Cross Hit@1 | Cross Hit@3 | Cross Hit@5 | Cross MRR | p95 CPU (ms) | RAM model+inference Δ (MB) |
|---|---|:---:|---: | ---: | ---:|---:|---: | ---: | ---:|---:|---:|---:|
| `bm25` | zeroshot | es | 0.437 | 0.654 | 0.760 | 0.556 | 0.225 | 0.356 | 0.407 | 0.296 | 0.2 | 0.8 |
| `bm25` | zeroshot | pt | 0.467 | 0.607 | 0.696 | 0.546 | 0.222 | 0.370 | 0.430 | 0.300 | 0.2 | 0.8 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | es | 0.437 | 0.617 | 0.686 | 0.532 | 0.422 | 0.600 | 0.684 | 0.517 | 7.9 | 1154.5 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | pt | 0.526 | 0.622 | 0.689 | 0.581 | 0.474 | 0.607 | 0.659 | 0.544 | 7.9 | 1154.5 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | es | 0.541 | 0.748 | 0.840 | 0.655 | 0.583 | 0.726 | 0.788 | 0.658 | 19.8 | 754.9 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | pt | 0.585 | 0.741 | 0.793 | 0.671 | 0.563 | 0.681 | 0.770 | 0.630 | 19.8 | 754.9 |

## Score Floor (0.81)

A question gets an answer when its best same- or cross-language score reaches the
floor, as kb.search does. **Lost** is the share of answerable questions left with no
result; **wrongly answered** is the share of questions the KB does not cover (no gold
snippet) that still get a result. BM25 and hybrid scores are not cosines and are
not listed.

| Candidate Model | Language | Answerable | Lost | Not covered | Wrongly answered |
|---|:---:|---:|---:|---:|---:|
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | es | 405 | 0.993 | 45 | 0.000 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | pt | 135 | 1.000 | 15 | 0.000 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | es | 405 | 0.005 | 45 | 0.089 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | pt | 135 | 0.015 | 15 | 0.067 |

## Evaluation Notes & Decisions

1. **Retrieval Baseline:** Evaluated against `bm25` lexical search.
2. **Dense Retrieval:** Evaluated using bi-encoder SentenceTransformers on CPU;
   `hybrid` fuses BM25 and the dense ranking with reciprocal rank fusion.
3. **Same-language (Hit@k, MRR):** the index is restricted to the query's language.
4. **Cross-language (Cross Hit@k, Cross MRR):** the same query against an index
   restricted to the other languages; gold is the query's topic in those
   languages. `n/a` when the KB snippets carry no `topic_id`.
5. **Latency & Resource Footprint:** Measured strictly on CPU (`device=cpu`).
