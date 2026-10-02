# Embedding Model Calibration Report

- **Scored split:** `test` (provenance: synthetic)
- **Date:** 2026-10-02
- **Task:** `embedding` (Knowledge Base Policy Retrieval)
- **Execution Environment:** Darwin 27.0.0 (arm64), Python 3.12.12, PyTorch 2.14.0 (host, 8 threads)
  (MPS/CUDA for training if available, CPU for inference benchmarking)

## Artifact Provenance & Hashes

- **Configuration:** `tools/calibrate/configs/embedding_regional_message.yaml` (`e38ef56963e64e8f9dbb550070fcef2043947a3272dd92b90fe097a489c3918a`)
- **Data Splits:**
- `packages/retrieval/kb/snippets.jsonl`: `25b9c7a8cba25d9102ae86f826c14ab93ce58bc3ecd92754b4719ad752f9b0ca`
- `data/eval/synthetic/retrieval/queries_regional.jsonl`: `8e2ca09878423186b3ed2d1c9623054a0457ce98585b01cc49c79de9e9f5e7a7`

## Calibration Summary Table

| Candidate Model | Mode | Language | Hit@1 | Hit@3 | Hit@5 | MRR | Cross Hit@1 | Cross Hit@3 | Cross Hit@5 | Cross MRR | p95 CPU (ms) | RAM model+inference Δ (MB) |
|---|---|:---:|---: | ---: | ---:|---:|---: | ---: | ---:|---:|---:|---:|
| `bm25` | zeroshot | es | 0.106 | 0.217 | 0.301 | 0.170 | 0.054 | 0.163 | 0.264 | 0.122 | 0.4 | 0.8 |
| `bm25` | zeroshot | pt | 0.148 | 0.244 | 0.348 | 0.215 | 0.133 | 0.237 | 0.304 | 0.195 | 0.4 | 0.8 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | es | 0.257 | 0.427 | 0.486 | 0.346 | 0.232 | 0.395 | 0.481 | 0.323 | 12.7 | 960.7 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | pt | 0.259 | 0.459 | 0.578 | 0.372 | 0.289 | 0.474 | 0.541 | 0.385 | 12.7 | 960.7 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | es | 0.348 | 0.570 | 0.686 | 0.471 | 0.370 | 0.548 | 0.664 | 0.471 | 29.5 | 1771.3 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | pt | 0.400 | 0.637 | 0.778 | 0.536 | 0.415 | 0.600 | 0.674 | 0.503 | 29.5 | 1771.3 |

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
| `ibm-granite/granite-embedding-311m-multilingual-r2` | es | 405 | 0.007 | 45 | 0.133 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | pt | 135 | 0.000 | 15 | 0.000 |

## Evaluation Notes & Decisions

1. **Retrieval Baseline:** Evaluated against `bm25` lexical search.
2. **Dense Retrieval:** Evaluated using bi-encoder SentenceTransformers on CPU;
   `hybrid` fuses BM25 and the dense ranking with reciprocal rank fusion.
3. **Same-language (Hit@k, MRR):** the index is restricted to the query's language.
4. **Cross-language (Cross Hit@k, Cross MRR):** the same query against an index
   restricted to the other languages; gold is the query's topic in those
   languages. `n/a` when the KB snippets carry no `topic_id`.
5. **Latency & Resource Footprint:** Measured strictly on CPU (`device=cpu`).
