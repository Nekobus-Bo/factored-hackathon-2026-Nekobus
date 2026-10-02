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

## Amendment (2026-09-29): the two zones on Cloud Run

On Cloud Run ([ADR-0015](0015-gcp-cloud-run-terraform.md)) the two Redis instances become two Memorystore instances, each with AUTH, and PostgreSQL becomes Cloud SQL with a private address only. "The orchestrator has no network path to `postgres` or `redis-core`" is kept by address and firewall instead of by Docker network: Cloud SQL and redis-core live in their own private-service-access range, and a firewall rule denies egress to it from every service tagged `pb-edge`; a network-check job verifies it on the real network. Cloud SQL supports pgvector; it is not created, because nothing uses it yet (the KB index is in `banking-core` memory, above).

## Amendment (2026-10-01): kb.search moves to granite-embedding-311m-multilingual-r2

**Context.** Two findings from the lab comparison of MiniLM against four retrieval-trained candidates ([docs/embedding-model-candidates.md](../embedding-model-candidates.md), `lab/notebooks/compare__kb-embeddings.py`, same KB, queries and metrics as the harness):

- **The MiniLM pin was broken.** Revision `86741b4e` holds the same weights as upstream's current commit, but its tokenizer config predates transformers v5. Under the 5.x this repo locks, it loads a `BertTokenizer` that maps most words to `<unk>`, and same-language Hit@1 falls to **0.050**. The 2026-09-27 evidence above loaded the default branch (the harness passes no revision), which already had the fix (`e8f8c211`), so it measured a model that was not the one deployed.
- **MiniLM is the weakest of the five even when fixed.** It was trained for paraphrase, not retrieval.

**Options.**
1. Move the MiniLM pin to `e8f8c211`.
2. Switch to `granite-embedding-97m-multilingual-r2`.
3. Switch to `granite-embedding-311m-multilingual-r2`.

All three need only configuration in the retrieval path: no prompts, sentence-transformers, no `trust_remote_code`, Apache 2.0, not gated. e5-small and Harrier were set aside: their prefixes add a code path and measured within noise, and neither beats granite-311m.

**Decision.** `kb.search` uses **`ibm-granite/granite-embedding-311m-multilingual-r2`**, revision `44399559930365213510b1ee2eb15ded83374f0e`, **loaded in fp32** (`EMBEDDING_DTYPE=float32`, the default). The model ships bf16 weights. fp32 costs twice the memory, but its CPU speed does not depend on bf16 support, which Cloud Run's x86 hosts may lack.

Lab evidence, pooled over the 360 validation queries (bf16, Apple Silicon CPU; Δ is the paired bootstrap 95% CI against the fixed MiniLM):

| Model | Same-language Hit@1 | MRR | Cross-language Hit@1 | Hit@1 Δ | p95 |
|---|---:|---:|---:|---|---:|
| MiniLM, pin `86741b4e` (was deployed) | 0.050 | 0.094 | 0.036 | −0.44 [−0.50, −0.39] | 6 ms |
| MiniLM, `e8f8c211` (fixed) | 0.494 | 0.605 | 0.508 | — | 6 ms |
| granite-97m | 0.614 | 0.727 | 0.600 | +0.12 [+0.06, +0.18] | 12 ms (p50) |
| **granite-311m** | **0.714** | **0.820** | **0.703** | **+0.22 [+0.17, +0.28]** | 37 ms |

Harness confirmation in fp32 (`make calibrate TASK=embedding CONFIG=tools/calibrate/configs/embedding_kb_v2.yaml`, report `reports/calibration-embedding-2026-10-02.md`, mean over es/pt/en):

| Backend | Same-language Hit@1 | Hit@5 | MRR | Cross-language Hit@1 | Cross MRR | p95 CPU (8 threads) |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.366 | 0.603 | 0.456 | 0.144 | 0.197 | 0.1 ms |
| MiniLM (`e8f8c211`, the fixed tokenizer) | 0.494 | 0.794 | 0.605 | 0.508 | 0.593 | 7.1 ms |
| **granite-311m, fp32** | **0.719** | **0.964** | **0.822** | **0.711** | **0.796** | 18.6 ms |

The report's RAM column comes from one process loading the candidates in turn, so it is not a per-model figure.

**Score floor** ([reports/embedding-score-floor-2026-10-02.md](../../reports/embedding-score-floor-2026-10-02.md)). Granite's cosine scores sit in a compressed band, so the MiniLM-era floor of 0.3 filters nothing. Top-1 same-language scores:

| | Lowest in-domain | Highest off-topic |
|---|---:|---:|
| Granite | 0.807 | 0.807 |
| MiniLM | — | 0.30 (median 0.13) |

For Granite, in-domain is the 360 validation queries (p5 0.84) and off-topic is 30 team-written queries (recipes, sport, weather; 10 per language). At 0.3 every off-topic query returned snippets. The seed moves to **`RETRIEVAL_SCORE_FLOOR=0.80`**:
- it keeps all 360 in-domain queries;
- it lets 1 of the 30 off-topic queries through, against 1 of 12 for MiniLM at 0.3;
- at 0.81, one in-domain query falls below the floor.

The margin is a few hundredths wide, so the floor stays provisional until a human-written test set with out-of-scope queries exists.

**Consequences.**
- Vectors grow from 384 to 768 dimensions. `banking-core` takes the dimension from the model server's first response, so the in-memory index needs no change; a future pgvector column must use 768.
- The encoder holds about 1.2 GB of fp32 weights for embeddings instead of about 0.45 GB, next to DistilBERT.
- One query takes tens of milliseconds instead of a few. That is small next to LLM latency.
- `RETRIEVAL_SCORE_FLOOR` moves from 0.3 to 0.80, a value tied to this model's score scale. Any later model change must re-derive it.

## Amendment (2026-10-02): regional test questions, floor 0.80 → 0.81

**Context.** The evidence above rests on one uniform synthetic set (360 questions, all answerable) and 30 team-written off-topic queries. A second, harder set now exists: `data/eval/synthetic/retrieval/queries_regional.jsonl`, 600 provisional questions. GPT Sol wrote them from real es-MX, es-AR, es-CO and pt-BR customer language (half-B style cards and masked phrases from `tools/synthdata_regional`). They include 60 out-of-scope banking and 60 off-topic questions, and each one comes with the query the orchestrator's LLM (gpt-6-luna) sends to `kb_search`. Construction: `data/eval/synthetic/retrieval/README.md` §6. Results: [reports/embedding-regional-2026-10-02.md](../../reports/embedding-regional-2026-10-02.md).

**Findings.**
- **Granite stays first in every locale and on both inputs.** On the production path (the LLM's query) it scores Hit@1 0.552, against MiniLM 0.459 and BM25 0.448. The decision of 2026-10-01 stands on questions that share far fewer words with the KB (BM25 Hit@1 on messages 0.12, against 0.37 on the older set).
- **The 0.80 floor let 17% of off-topic questions through** on the production path (10 of 60), against 3% on the earlier 30.

**Decision.** `RETRIEVAL_SCORE_FLOOR` seed **0.81**: in `.env.example`, compose, Terraform and the `KbSearchConfig` default. On the production path it:
- keeps all 480 answerable in-scope questions;
- cuts off-topic answers to 8%;
- costs 7% of out-of-scope banking questions their scope snippet (the LLM can still decline those itself).

At 0.82 and above, answerable questions start going unanswered (5 of 480 at 0.82).

**Consequences.** The floor is still provisional: the set is LLM-written and not reviewed by a human, and each locale has only 30 not-covered questions. A human-written set with out-of-scope questions must re-derive it. The harness now reports the floor's effect directly (`score_floor` in the embedding config).
- The evidence is still the provisional synthetic set; the human-written test set re-checks it.

## Action items

1. [ ] Migrations with the three schemas
2. [ ] Knowledge base ingestion with offline embeddings
3. [x] Experiment: BM25 vs vector vs hybrid, results in `evaluation.md` (2026-09-27, provisional query set)
4. [ ] Hash-chained audit log and verifier
5. [ ] Reproducible seeds from the dataset
