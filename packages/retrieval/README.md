# Retrieval Package

Lexical and dense retrieval adapters (BM25 and SentenceTransformers) for banking policies.

## Knowledge base and search

- `KnowledgeBase.from_jsonl()` loads `kb/snippets.jsonl` and validates it: unique ids, `lang` in es/pt/en, and `id == "<topic_id>.<lang>"`.
- `Retriever(kb, adapter).search(query, lang, k, mode)` ranks the whole KB with one index and filters by language: `SearchMode.SAME` (default, only the query's language), `CROSS` (only the other languages) or `ANY`.
- Backends: `BM25Adapter`, `SentenceTransformersAdapter` (dense, CPU) and `HybridAdapter` (reciprocal rank fusion of the two).

The backend comparison and the default choice are in [ADR-0006](../../docs/adr/0006-single-postgres-pgvector.md) and [evaluation.md](../../docs/evaluation.md#knowledge-retrieval).
