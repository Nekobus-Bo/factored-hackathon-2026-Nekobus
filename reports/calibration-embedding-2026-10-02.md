# Embedding Model Calibration Report

- **Scored split:** `validation` (provenance: synthetic)
- **Date:** 2026-10-02
- **Task:** `embedding` (Knowledge Base Policy Retrieval)
- **Execution Environment:** Darwin 27.0.0 (arm64), Python 3.12.12, PyTorch 2.14.0 (host, 8 threads)
  (MPS/CUDA for training if available, CPU for inference benchmarking)

## Artifact Provenance & Hashes

- **Configuration:** `tools/calibrate/configs/embedding_kb_v2.yaml` (`a749e54ff69ded33cfcb7dd08c6418d488b8854afc90024b14f01a2cd16808a7`)
- **Data Splits:**
- `packages/retrieval/kb/snippets.jsonl`: `25b9c7a8cba25d9102ae86f826c14ab93ce58bc3ecd92754b4719ad752f9b0ca`
- `data/eval/synthetic/retrieval/queries.jsonl`: `c36e0de2f1fa61d6dd1f0f9527143eef3b052644d73a7e70ce0cd662f5b3a5a4`

## Calibration Summary Table

| Candidate Model | Mode | Language | Hit@1 | Hit@3 | Hit@5 | MRR | Cross Hit@1 | Cross Hit@3 | Cross Hit@5 | Cross MRR | p95 CPU (ms) | RAM model+inference Δ (MB) |
|---|---|:---:|---: | ---: | ---:|---:|---: | ---: | ---:|---:|---:|---:|
| `bm25` | zeroshot | es | 0.333 | 0.458 | 0.558 | 0.414 | 0.158 | 0.317 | 0.383 | 0.237 | 0.1 | 0.9 |
| `bm25` | zeroshot | pt | 0.383 | 0.525 | 0.583 | 0.458 | 0.183 | 0.250 | 0.300 | 0.224 | 0.1 | 0.9 |
| `bm25` | zeroshot | en | 0.383 | 0.592 | 0.667 | 0.495 | 0.092 | 0.142 | 0.217 | 0.131 | 0.1 | 0.9 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | es | 0.492 | 0.650 | 0.750 | 0.591 | 0.525 | 0.667 | 0.775 | 0.611 | 7.1 | 1155.8 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | pt | 0.458 | 0.650 | 0.808 | 0.578 | 0.533 | 0.642 | 0.725 | 0.602 | 7.1 | 1155.8 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | zeroshot | en | 0.533 | 0.767 | 0.825 | 0.646 | 0.467 | 0.658 | 0.750 | 0.566 | 7.1 | 1155.8 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | es | 0.658 | 0.933 | 0.967 | 0.797 | 0.708 | 0.842 | 0.958 | 0.790 | 18.6 | 463.6 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | pt | 0.758 | 0.950 | 0.983 | 0.851 | 0.725 | 0.900 | 0.950 | 0.815 | 18.6 | 463.6 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | zeroshot | en | 0.742 | 0.883 | 0.942 | 0.817 | 0.700 | 0.875 | 0.908 | 0.783 | 18.6 | 463.6 |

## Evaluation Notes & Decisions

1. **Retrieval Baseline:** Evaluated against `bm25` lexical search.
2. **Dense Retrieval:** Evaluated using bi-encoder SentenceTransformers on CPU;
   `hybrid` fuses BM25 and the dense ranking with reciprocal rank fusion.
3. **Same-language (Hit@k, MRR):** the index is restricted to the query's language.
4. **Cross-language (Cross Hit@k, Cross MRR):** the same query against an index
   restricted to the other languages; gold is the query's topic in those
   languages. `n/a` when the KB snippets carry no `topic_id`.
5. **Latency & Resource Footprint:** Measured strictly on CPU (`device=cpu`).
