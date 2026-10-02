# Embedding model candidates for `kb.search`

As of 2026-10-01. A desk investigation of models that could replace `paraphrase-multilingual-MiniLM-L12-v2`, the model behind `kb.search` ([embeddings.md](embeddings.md)).

**Status: decided on 2026-10-01.** `granite-embedding-311m-multilingual-r2`, loaded in fp32, replaced MiniLM after it beat it in the lab comparison (`lab/notebooks/compare__kb-embeddings.py`) and in the calibration harness ([report](../reports/calibration-embedding-2026-10-02.md)): same-language Hit@1 0.719 against 0.494, cross-language 0.711 against 0.508. The decision is the [ADR-0006](adr/0006-single-postgres-pgvector.md) amendment of 2026-10-01. The tables below are the desk research that chose the candidates; they come from public benchmarks (MTEB), not from our knowledge base.

## Conclusions

1. **MiniLM is outclassed.** It was trained for paraphrase, not retrieval. In the Granite R2 paper's 5-benchmark multilingual average it scores 26.1, the lowest of 14 models, against 39–54 for the alternatives.
2. **`granite-embedding-97m-multilingual-r2` is the first model to test.** Apache 2.0, smaller than MiniLM, the same 384 dimensions, no prompts, so switching is a configuration change only.
3. **`granite-embedding-311m-multilingual-r2` is the stronger fallback.** It also needs no code change, scores about 5 points higher, and is about 3× the size.
4. **`harrier-oss-v1-270m` has the best score in its size class**, but needs a query instruction and its CPU memory and latency are unknown. Post-freeze.
5. **`multilingual-e5-small` and `bge-m3` are not the best fit.** e5-small needs prefixes and scores below both Granite models. bge-m3 would not fit the encoder's memory budget.

## What a candidate must meet

| Requirement | Why |
|---|---|
| Multilingual: es, pt, en, including cross-language matching | Customers and KB use all three; `kb.search` falls back to other languages (CROSS) |
| Small enough for CPU | [ADR-0008](adr/0008-cpu-inference-deployment.md): the encoder has a 3 GB limit shared with the DistilBERT decision model (446 MiB measured) |
| Loads with sentence-transformers, no `trust_remote_code` | `SentenceTransformersAdapter` loads models that way. Remote code would run unpinned Python inside the model server and weaken the revision and hash pins |
| Open weights, commercial license, no gated download | `make warmup-retrieval` and the Cloud Run build download weights without logging in |
| Beats MiniLM in our harness | Same-language Hit@1 0.494, cross-language Hit@1 0.508 ([report](../reports/calibration-embedding-2026-09-27.md)) |

## Comparison

| | **MiniLM-L12-v2** (current) | **multilingual-e5-small** | **granite-97m-r2** | **granite-311m-r2** | **harrier-oss-v1-270m** |
|---|---|---|---|---|---|
| Publisher | sentence-transformers | Microsoft (intfloat) | IBM | IBM | Microsoft |
| License | Apache 2.0 | MIT | Apache 2.0 | Apache 2.0 | MIT |
| Parameters | ~118M | ~118M (paper lists 96M) | 97M | 311M | 270M |
| Weights on disk | 471 MB (fp32) | 471 MB (fp32) | 195 MB (16-bit) | 623 MB (16-bit) | 536 MB (16-bit) |
| Dimensions | 384 | 384 | 384 | 768 (Matryoshka down to 128) | 640 |
| Max tokens | 128 | 512 | 32,768 | 32,768 | 32,768 |
| Architecture | BERT encoder | XLM-R encoder | ModernBERT encoder | ModernBERT encoder | Decoder, last-token pooling |
| Trained for retrieval | No (paraphrase) | Yes | Yes | Yes | Yes |
| MTEB multilingual retrieval (18 tasks, NDCG@10) | — | 50.9 | 60.3 | 65.2 | **66.4** |
| MTEB English retrieval (10 tasks) | — | 46.5 | 50.1 | **52.6** | 52.1 |
| 5-benchmark average (Granite paper, Figure 1) | 26.1 | 39.1 | 50.2 | **54.4** | 54.1 |
| Prompts needed | No | `query: ` / `passage: ` on every text | No | No | Instruction on queries only |
| `trust_remote_code` | No | No | No | No | No |
| Change to adopt | — | Config + prefix option | **Config only** | **Config only** | Config + prefix option |
| Memory risk (encoder 3 GB limit) | Baseline | Same as now | Lowest | Moderate | Moderate to high; measure |

## Also looked at and set aside

| Model | Why not |
|---|---|
| `BAAI/bge-m3` (568M, 1024 dims, MIT, no prompts) | 2.27 GB of fp32 weights, about 5× MiniLM. It would not fit next to DistilBERT under the 3 GB limit (about 5 GB needed), and XLM-R large on CPU will be several times slower. Its strengths (8k-token documents, sparse and multi-vector modes) don't apply to 40–120-word snippets with dense-only search. No score comparable with Table 5 was found |
| `jinaai/jina-embeddings-v5-text-nano` (63.3) | CC-BY-NC-4.0 (non-commercial) and needs `trust_remote_code` |
| `google/embeddinggemma-300m` (62.5) | Gemma license with a gated download, and needs query and document prompts |
| `Alibaba-NLP/gte-multilingual-base`, `Snowflake/snowflake-arctic-embed-m-v2.0` (57.2, 54.8) | Lower scores; believed to need `trust_remote_code` (not checked on their cards) |
| Models above ~600M parameters | Too large for the CPU encoder budget (ADR-0008) |

## Learnings

- **Prefixes and instructions don't need a contract change.** In [remote_embedding.py](../packages/retrieval/src/retrieval/adapters/remote_embedding.py), `index()` builds snippet texts and `search()` builds query texts separately. A configurable `query_prefix` and `passage_prefix` on the adapters (plus the calibration harness) covers e5 and harrier. The model server and `/v1/embed` stay unchanged.
- **Disk size isn't memory.** MiniLM and e5 ship fp32 weights; the Granite and Harrier files are 16-bit. If loaded as fp32, their RAM roughly doubles. Only the harness's RAM column settles it.
- **MTEB isn't our task.** MTEB averages over Wikipedia, web and long-document retrieval. Ours is casual customer messages against 120 short policy snippets. A leaderboard score earns a place in our harness, nothing more.
- **Long context is irrelevant here.** The 32k-token windows of Granite and Harrier add nothing for 40–120-word snippets.
- **Our library versions are recent enough** (sentence-transformers 6.1.0, transformers 5.16.1, torch 2.14.0), so ModernBERT and decoder-based embedders load.
- **The leaderboard page can't be scraped.** It is a JavaScript app. The Granite R2 paper's Table 5 reprints its multilingual retrieval scores for small models, and model cards give license, size and prompt needs.

## Next steps

1. Copy [embedding_kb_v1.yaml](../tools/calibrate/configs/embedding_kb_v1.yaml) and add `granite-embedding-97m-multilingual-r2` and `granite-embedding-311m-multilingual-r2` as `sentence_transformers` candidates next to BM25 and MiniLM. No code change.
2. Run `make calibrate TASK=embedding CONFIG=<new config>` and commit the report to `reports/`.
3. Compare same-language and cross-language Hit@1 and MRR, p95 latency and RAM. Remember the ~0.09 Hit@1 noise band at 120 queries per language.
4. If a model wins, add an ADR-0006 amendment, update `EMBEDDING_MODEL`, `EMBEDDING_REVISION` and `EMBEDDING_WEIGHTS_SHA256` in `.env.example` and [variables.tf](../infra/deploy/gcp/variables.tf), run `make warmup-retrieval`, and update [embeddings.md](embeddings.md) and [limitations.md](limitations.md).
5. After the freeze: add the prefix option, then test `harrier-oss-v1-270m` and `multilingual-e5-small`.

The code freeze is 2026-10-04 at noon. Steps 1–4 fit only if the report is ready before then.

## Open questions

- Actual RAM and p95 latency of each candidate on the Linux encoder container.
- Whether Granite's 16-bit weights load as fp32 by default in our adapter.
- Whether any candidate's gain holds on a human-written test set; ours is synthetic and favors vector models over BM25.

## Sources

- [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
- [Granite Embedding Multilingual R2 Models (arXiv 2605.13521)](https://arxiv.org/pdf/2605.13521): Table 5 and Figure 1
- Model cards: [granite-embedding-97m-multilingual-r2](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2), [granite-embedding-311m-multilingual-r2](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2), [harrier-oss-v1-270m](https://huggingface.co/microsoft/harrier-oss-v1-270m), [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small), [bge-m3](https://huggingface.co/BAAI/bge-m3), [jina-embeddings-v5-text-nano](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano), [embeddinggemma-300m](https://huggingface.co/google/embeddinggemma-300m), [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
- Weight sizes: Hugging Face file headers (`x-linked-size`), 2026-10-01
