from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from retrieval.base import RetrievalAdapter
from retrieval.models import KBSnippet, QueryExample

DEFAULT_RRF_K = 60


class HybridAdapter(RetrievalAdapter):
    """Reciprocal rank fusion of a lexical and a dense adapter.

    Each backend ranks the whole indexed corpus; a snippet's fused score is
    ``sum(1 / (rrf_k + rank))`` over the backends (rank starts at 1). Ties are
    broken by snippet id so results are deterministic.
    """

    def __init__(
        self,
        lexical: RetrievalAdapter,
        dense: RetrievalAdapter,
        rrf_k: int = DEFAULT_RRF_K,
        name: str = "hybrid_rrf",
    ) -> None:
        if rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        self.name = name
        self.lexical = lexical
        self.dense = dense
        self.rrf_k = rrf_k
        self._corpus_size = 0

    def index(self, kb: Sequence[KBSnippet]) -> None:
        self.lexical.index(kb)
        self.dense.index(kb)
        self._corpus_size = len(kb)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        fused: dict[str, float] = {}
        for backend in (self.lexical, self.dense):
            ranking = backend.search(query, top_k=self._corpus_size)
            for rank, (doc_id, _) in enumerate(ranking, 1):
                fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (self.rrf_k + rank)
        ordered = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
        return ordered[:top_k]

    def fit(
        self,
        queries: Sequence[QueryExample],
        kb: Sequence[KBSnippet],
        val_queries: Sequence[QueryExample] | None = None,
        epochs: int = 1,
        batch_size: int = 8,
        learning_rate: float = 2e-5,
    ) -> None:
        """Fit both backends; the fusion itself has no trainable state."""
        for backend in (self.lexical, self.dense):
            backend.fit(queries, kb, val_queries, epochs, batch_size, learning_rate)
        self._corpus_size = len(kb)

    def save(self, path: str | Path) -> None:
        raise NotImplementedError(
            "HybridAdapter has no state of its own; save its lexical and dense "
            "backends separately"
        )

    def load(self, path: str | Path) -> None:
        raise NotImplementedError(
            "HybridAdapter has no state of its own; load its lexical and dense "
            "backends separately"
        )
