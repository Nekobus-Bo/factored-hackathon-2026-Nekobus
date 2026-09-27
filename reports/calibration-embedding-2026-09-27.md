# Embedding Model Calibration Report

- **Date:** 2026-09-27
- **Task:** `embedding` (Knowledge Base Policy Retrieval)
- **Evaluated split:** `validation`
- **Execution Environment:** Darwin 27.0.0 (arm64), Python 3.12.14, PyTorch 2.14.0 (host, 4 threads)
  (MPS/CUDA for training if available, CPU for inference benchmarking)

## Artifact Provenance & Hashes

- **Configuration:** `tools/calibrate/configs/embedding_kb_v1.yaml` (`1c71a6aed8581c9364055ce75a94a6b61030d18d451f36d7d5a1c49a0600a2ea`)
- **Data Splits:**
- `packages/retrieval/kb/snippets.jsonl`: `25b9c7a8cba25d9102ae86f826c14ab93ce58bc3ecd92754b4719ad752f9b0ca`
- `data/eval/synthetic/retrieval/queries.jsonl`: `c36e0de2f1fa61d6dd1f0f9527143eef3b052644d73a7e70ce0cd662f5b3a5a4`

## Calibration Summary Table

| Candidate Model | Mode | Language | Hit@1 | Hit@3 | Hit@5 | MRR | Cross Hit@1 | Cross Hit@3 | Cross Hit@5 | Cross MRR | p95 CPU (ms) | RAM model+inference Δ (MB) |
|---|---|:---:|---: | ---: | ---:|---:|---: | ---: | ---:|---:|---:|---:|
| `bm25` | zeroshot | es | 0.333 | 0.458 | 0.558 | 0.414 | 0.158 | 0.317 | 0.383 | 0.237 | 0.2 | 0.8 |
| `bm25` | zeroshot | pt | 0.383 | 0.525 | 0.583 | 0.458 | 0.183 | 0.250 | 0.300 | 0.224 | 0.2 | 0.8 |
| `bm25` | zeroshot | en | 0.383 | 0.592 | 0.667 | 0.495 | 0.092 | 0.142 | 0.217 | 0.131 | 0.2 | 0.8 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | es | 0.492 | 0.650 | 0.750 | 0.591 | 0.525 | 0.667 | 0.775 | 0.611 | 7.8 | 832.9 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | pt | 0.458 | 0.650 | 0.808 | 0.578 | 0.533 | 0.642 | 0.725 | 0.602 | 7.8 | 832.9 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | en | 0.533 | 0.767 | 0.825 | 0.646 | 0.467 | 0.658 | 0.750 | 0.566 | 7.8 | 832.9 |
| `hybrid_rrf(bm25 + sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)` | zeroshot | es | 0.400 | 0.667 | 0.775 | 0.548 | 0.342 | 0.658 | 0.792 | 0.511 | 7.2 | 330.1 |
| `hybrid_rrf(bm25 + sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)` | zeroshot | pt | 0.433 | 0.700 | 0.800 | 0.578 | 0.333 | 0.583 | 0.733 | 0.463 | 7.2 | 330.1 |
| `hybrid_rrf(bm25 + sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)` | zeroshot | en | 0.550 | 0.733 | 0.800 | 0.646 | 0.300 | 0.550 | 0.683 | 0.440 | 7.2 | 330.1 |

## Evaluation Notes & Decisions

1. **Retrieval Baseline:** Evaluated against `bm25` lexical search.
2. **Dense Retrieval:** Evaluated using bi-encoder SentenceTransformers on CPU;
   `hybrid` fuses BM25 and the dense ranking with reciprocal rank fusion.
3. **Same-language (Hit@k, MRR):** the index is restricted to the query's language.
4. **Cross-language (Cross Hit@k, Cross MRR):** the same query against an index
   restricted to the other languages; gold is the query's topic in those
   languages. `n/a` when the KB snippets carry no `topic_id`.
5. **Latency & Resource Footprint:** Measured strictly on CPU (`device=cpu`).
