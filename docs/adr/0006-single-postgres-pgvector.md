# ADR-0006: A single PostgreSQL with pgvector, plus Redis

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

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

## Action items

1. [ ] Migrations with the three schemas
2. [ ] Knowledge base ingestion with offline embeddings
3. [ ] Experiment: BM25 vs vector vs hybrid, results in `evaluation.md`
4. [ ] Hash-chained audit log and verifier
5. [ ] Reproducible seeds from the dataset
