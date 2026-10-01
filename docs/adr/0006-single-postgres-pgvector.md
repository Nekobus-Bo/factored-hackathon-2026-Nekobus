# ADR-0006: A single PostgreSQL with pgvector, plus Redis

**Status:** Accepted · amended 2026-09-29 · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

The system needs relational data (customers, accounts, cards, transactions, tickets), semantic search over the knowledge base, and ephemeral session state and caching. In 10 days, every additional engine is one more thing to deploy, monitor and explain.

## Decision

- **One PostgreSQL instance** with a vector extension, split into schemas: `core_bank`, `chat`, `ops`.
- **Redis** for caching, ephemeral session state, rate limiting and job queues.
- **Hybrid search**: full-text index (BM25) combined with vector search, with the mix decided by evidence rather than by default.
- **Append-only audit log** with hash chaining: every row includes the hash of the previous one, making any later alteration detectable.

## Options considered

### Option A: Postgres + a dedicated vector database

| Dimension | Assessment |
|---|---|
| Complexity | High: two engines, two backups, consistency between them |
| Cost | Higher |
| Benefit at this scale | Marginal |

**Pros:** better vector performance at large volume; richer filtering.
**Cons:** our knowledge base is hundreds of snippets, not millions; syncing two stores adds failure modes with no measurable benefit.

### Option B (chosen): a single Postgres with a vector extension

**Pros:** one transaction covers data and embeddings; a single backup; judges bring up fewer containers; allows lexical + vector hybrid in one query.
**Cons:** lower performance ceiling at scale; less flexible vector index tuning.

### Option C: in-memory / files

Rejected: does not support the production argument or the audit requirement.

## Trade-off analysis

At our scale the bottleneck is LLM latency, not vector search. Optimizing the vector store would be optimizing what does not hurt. Also, with a small knowledge base **lexical search often beats semantic**, and keeping both in the same engine lets us measure the mix instead of assuming it — reported in `evaluation.md`.

### Scaling path (documented, not implemented)

1. Read replica for analytics and the back office.
2. Physical separation of the hot schema via logical replication.
3. Move the vector index to a dedicated engine if volume justifies it.
4. Partition transactions by date.

## Consequences

**Becomes easier:** operating, backing up and reproducing; queries that span business and semantic data.

**Becomes harder:** isolating workloads — a heavy report can affect the transactional path until there is a replica.

**To revisit:** if hybrid search does not beat BM25 alone, the vector component is removed and that is documented. We do not keep parts that fail to earn their place in the measurement.

## Amendment (2026-09-26): one Redis per trust zone

The single Redis in the decision above is split in two, following the trust boundary of [ADR-0004](0004-trust-boundary.md):

- **`redis-core`** — used only by `banking-core`: pinned account holder, FSM state, attempt limits, idempotency keys. Lives on the internal `core` network together with `postgres`.
- **`redis-edge`** — used only by `orchestrator`: chat session and cache. Lives on the `edge` network.

**Why:** with one shared, unauthenticated Redis, a compromised `orchestrator` could rewrite the pinned holder or reset OTP and match counters, which voids the boundary. Each Redis has its own password, and the `orchestrator` has no network path to `postgres` or `redis-core`. This is still one engine to operate; the cost is a second container.

## Amendment (2026-09-27): retrieval evidence — keep the vector index

Measured with the calibration harness (`make calibrate TASK=embedding CONFIG=tools/calibrate/configs/embedding_kb_v1.yaml`), report `reports/calibration-embedding-2026-09-27.md`; summary in [evaluation.md](../evaluation.md#knowledge-retrieval). Mean over es/pt/en, 120 provisional synthetic validation queries per language:

| Backend | Same-language Hit@1 | Same-language MRR | Cross-language Hit@1 |
|---|---:|---:|---:|
| BM25 | 0.366 | 0.456 | 0.144 |
| Vector (`paraphrase-multilingual-MiniLM-L12-v2`) | 0.494 | 0.605 | 0.508 |
| Hybrid (RRF, k=60) | 0.461 | 0.591 | 0.325 |

**Decision:** hybrid beats BM25, so the vector component is **kept**, as this ADR required. The **default backend is vector-only**: equal-weight RRF adds nothing over vector on same-language queries (differences within sampling noise) and loses 0.18 Hit@1 cross-language, because BM25 cannot match across languages and drags the fusion down. BM25 stays available as the baseline and as a component for a future weighted fusion.

**Caveats:** the query set is synthetic and provisional, and was written to avoid the KB's wording, which penalizes BM25. The decision is re-checked when the human-written test set exists. Weighted fusion and per-language BM25 were not tried.

## Amendment (2026-09-29): the embedding model moves to the model server

[ADR-0012](0012-decision-points.md) (Appendix J) takes the embedding model out of `banking-core`. `kb.search` keeps the index it has (the 120-snippet KB held in `banking-core` memory) and the vector-only default above, but the vectors now come from `POST /v1/embed` on the model server (`apps/encoder`, deployable on its own host in the team's private network). The model and its revision are pinned; `banking-core` checks both on every response, and a mismatch or an unreachable server makes `kb.search` unavailable, never a fallback to BM25. The retrieval evidence above is unchanged: same model, same vectors. The in-process adapter stays for tests and local development (`EMBEDDING_BACKEND=local`) and is not wired in compose.

**Why:** one place where the embedding and decision models are pinned and calibrated, and no ~1.3 GB model in every `banking-core` replica. **Cost:** a small request per `kb.search`, and a dependency of the trusted zone on the model server that is integrity-only and carries public data (a compromised server can only make `kb.search` pick a wrong public snippet). pgvector ingestion of the KB stays pending.

## Action items

1. [ ] Migrations with the three schemas
2. [ ] Knowledge base ingestion with offline embeddings
3. [x] Experiment: BM25 vs vector vs hybrid, results in `evaluation.md` (2026-09-27, provisional query set)
4. [ ] Hash-chained audit log and verifier
5. [ ] Reproducible seeds from the dataset
