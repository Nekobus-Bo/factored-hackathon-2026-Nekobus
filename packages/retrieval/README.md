# Retrieval Package

Lexical and dense retrieval adapters (BM25 and SentenceTransformers) for banking policies.

## Knowledge base and search

- `KnowledgeBase.from_jsonl()` loads `kb/snippets.jsonl` and validates it: unique ids, `lang` in es/pt/en, and `id == "<topic_id>.<lang>"`.
- `Retriever(kb, adapter).search(query, lang, k, mode)` ranks the whole KB with one index and filters by language: `SearchMode.SAME` (default, only the query's language), `CROSS` (only the other languages) or `ANY`.
- Backends: `BM25Adapter`, `SentenceTransformersAdapter` (dense, CPU) and `HybridAdapter` (reciprocal rank fusion of the two).
- `RemoteEmbeddingAdapter` is the dense backend of `banking-core`: the same ranking as `SentenceTransformersAdapter`, but the vectors come from the model server's `POST /v1/embed` ([ADR-0012](../../docs/adr/0012-decision-points.md), Appendix J). It checks the pinned `model_id` and `revision` on every response, refuses malformed vectors, and needs neither PyTorch nor the `vector` extra. `SentenceTransformersAdapter.embed` is the function the model server runs.

The backend comparison and the default choice are in [ADR-0006](../../docs/adr/0006-single-postgres-pgvector.md) and [evaluation.md](../../docs/evaluation.md#knowledge-retrieval).
