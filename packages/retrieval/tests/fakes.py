"""Test-only retrieval adapters with fixed rankings."""

from collections.abc import Sequence
from pathlib import Path

from retrieval import KBSnippet, QueryExample, RetrievalAdapter


class FixedRankingAdapter(RetrievalAdapter):
    """Returns the same ranking for every query, restricted to indexed ids."""

    def __init__(self, ranking: Sequence[str], name: str = "fixed") -> None:
        self.name = name
        self.ranking = list(ranking)
        self.indexed: list[str] = []
        self.fitted = False

    def index(self, kb: Sequence[KBSnippet]) -> None:
        self.indexed = [s.id for s in kb]

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        ranked = [doc for doc in self.ranking if doc in self.indexed]
        return [(doc, float(len(ranked) - i)) for i, doc in enumerate(ranked)][:top_k]

    def fit(
        self,
        queries: Sequence[QueryExample],
        kb: Sequence[KBSnippet],
        val_queries: Sequence[QueryExample] | None = None,
        epochs: int = 1,
        batch_size: int = 8,
        learning_rate: float = 2e-5,
    ) -> None:
        self.fitted = True
        self.index(kb)

    def save(self, path: str | Path) -> None:
        raise NotImplementedError

    def load(self, path: str | Path) -> None:
        raise NotImplementedError
