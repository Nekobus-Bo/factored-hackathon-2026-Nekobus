"""Implementation of kb.search tool in banking-core.

Permitted in every verification state; the KB is public and carries no PII.
The index is built once per process (get_kb_searcher) from the configured JSONL.

Backends: vector is the default (ADR-0006). It needs the `vector` extra and the
embedding model in the local Hugging Face cache; if either is missing the
searcher fails loudly instead of falling back to BM25. BM25 or hybrid run only
when configured explicitly.

Language: the customer's language first (SAME); cross-language (CROSS) only
when SAME returns nothing at or above the configured score floor.

Scores are normalized to the contract's [0, 1]: cosine is clipped, BM25 is
divided by the best score over the whole KB, and RRF by its maximum 2/(k+1).
"""

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from contracts.tools.kb_search import (
    KbSearchInput,
    KbSearchOutput,
    KbSearchResultItem,
)
from retrieval import (
    BM25Adapter,
    HybridAdapter,
    KnowledgeBase,
    RetrievalAdapter,
    Retriever,
    SearchMode,
)

from banking_core.knowledge.config import KbSearchConfig

_SNIPPET_MAX = 2000
_TITLE_MAX = 200


class KbSearchUnavailableError(RuntimeError):
    """The configured backend cannot run (missing extra, model or KB file)."""


def resolve_local_model(model: str) -> str:
    """Return a local path for the model without touching the network."""
    if Path(model).is_dir():
        return model
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise KbSearchUnavailableError(
            "vector kb.search needs the 'vector' extra (banking-core[vector])"
        ) from exc
    try:
        return snapshot_download(model, local_files_only=True)
    except Exception as exc:
        raise KbSearchUnavailableError(
            f"embedding model '{model}' is not in the local cache; "
            "download it before starting (make warmup)"
        ) from exc


def _dense_adapter(config: KbSearchConfig) -> RetrievalAdapter:
    try:
        from retrieval.adapters.sentence_transformers import (
            SentenceTransformersAdapter,
        )
    except ImportError as exc:
        raise KbSearchUnavailableError(
            "vector kb.search needs the 'vector' extra (banking-core[vector])"
        ) from exc
    local_path = resolve_local_model(config.embedding_model)
    return SentenceTransformersAdapter(model_id=local_path)


def build_adapter(config: KbSearchConfig) -> RetrievalAdapter:
    """Adapter for the configured backend; never a silent substitute."""
    if config.backend == "bm25":
        return BM25Adapter()
    if config.backend == "hybrid":
        return HybridAdapter(lexical=BM25Adapter(), dense=_dense_adapter(config))
    return _dense_adapter(config)


class KbSearcher:
    """An indexed KB plus the language fallback and score normalization."""

    def __init__(
        self, config: KbSearchConfig, adapter: RetrievalAdapter | None = None
    ) -> None:
        self.config = config
        try:
            kb = KnowledgeBase.from_jsonl(config.kb_path)
        except OSError as exc:
            raise KbSearchUnavailableError(
                f"knowledge base not readable at '{config.kb_path}'"
            ) from exc
        self.adapter = adapter or build_adapter(config)
        self.retriever = Retriever(kb, self.adapter)
        self.kb = kb

    def _normalizer(self, query: str) -> Callable[[float], float]:
        if isinstance(self.adapter, BM25Adapter):
            top = self.adapter.search(query, top_k=1)
            best = top[0][1] if top else 0.0
            return lambda s: 0.0 if best <= 0 else s / best
        if isinstance(self.adapter, HybridAdapter):
            ceiling = 2.0 / (self.adapter.rrf_k + 1)
            return lambda s: s / ceiling
        return lambda s: s

    def search(self, args: KbSearchInput) -> KbSearchOutput:
        lang = args.locale.split("-")[0]
        k = min(args.limit, self.config.max_k)
        normalize = self._normalizer(args.query)

        items: list[KbSearchResultItem] = []
        for mode in (SearchMode.SAME, SearchMode.CROSS):
            hits = self.retriever.search(args.query, lang=lang, k=k, mode=mode)
            items = [
                self._item(hit.snippet_id, score)
                for hit in hits
                if (score := min(1.0, max(0.0, normalize(hit.score))))
                >= self.config.score_floor
            ]
            if items:
                break
        return KbSearchOutput(results=items)

    def _item(self, snippet_id: str, score: float) -> KbSearchResultItem:
        snippet = self.kb.get(snippet_id)
        topic = snippet.topic_id or "general"
        return KbSearchResultItem(
            article_id=snippet.id,
            title=snippet.title[:_TITLE_MAX],
            snippet=snippet.text[:_SNIPPET_MAX],
            category=topic.split(".")[0],
            score=round(score, 4),
        )


@lru_cache(maxsize=1)
def get_kb_searcher() -> KbSearcher:
    """Process-wide searcher built once from the environment configuration."""
    return KbSearcher(KbSearchConfig.from_env())


def execute_kb_search(
    args: KbSearchInput, searcher: KbSearcher | None = None
) -> KbSearchOutput:
    """Search the public KB; no holder, no session data, no PII."""
    return (searcher or get_kb_searcher()).search(args)
