from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from retrieval.models import KBSnippet, QueryExample


class RetrievalAdapter(ABC):
    """Abstract interface for knowledge base retrieval adapters."""

    name: str

    @abstractmethod
    def index(self, kb: Sequence[KBSnippet]) -> None:
        """Index all snippets in the knowledge base."""

    @abstractmethod
    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Retrieve top_k snippet IDs with their relevance scores."""

    @abstractmethod
    def fit(
        self,
        queries: Sequence[QueryExample],
        kb: Sequence[KBSnippet],
        val_queries: Sequence[QueryExample] | None = None,
        epochs: int = 1,
        batch_size: int = 8,
        learning_rate: float = 2e-5,
    ) -> None:
        """Fine-tune the retrieval model on query-document pairs."""

    @abstractmethod
    def save(self, path: str | Path) -> None:
        """Save adapter weights or indices."""

    @abstractmethod
    def load(self, path: str | Path) -> None:
        """Load adapter weights or indices."""
