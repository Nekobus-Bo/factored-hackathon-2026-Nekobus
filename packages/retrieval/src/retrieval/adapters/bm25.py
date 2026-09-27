from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import joblib
import numpy as np
from rank_bm25 import BM25Okapi

from retrieval.base import RetrievalAdapter
from retrieval.models import KBSnippet, QueryExample


def tokenize(text: str) -> list[str]:
    """Tokenize multilingual text into lowercased alphanumeric words."""
    return re.findall(r"\w+", text.lower())


class BM25Adapter(RetrievalAdapter):
    """Lexical baseline retrieval adapter based on BM25 Okapi."""

    def __init__(self, name: str = "bm25") -> None:
        self.name = name
        self.doc_ids: list[str] = []
        self.corpus: list[str] = []
        self.bm25: BM25Okapi | None = None

    def index(self, kb: Sequence[KBSnippet]) -> None:
        """Build BM25 index over combined title and body of all snippets."""
        self.doc_ids = [s.id for s in kb]
        self.corpus = [f"{s.title} {s.text}" for s in kb]
        tokenized_corpus = [tokenize(text) for text in self.corpus]
        self.bm25 = BM25Okapi(tokenized_corpus)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Rank indexed snippets for query."""
        if not self.bm25 or not self.doc_ids:
            return []

        tokenized_query = tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        ranked_indices = np.argsort(scores)[::-1][:top_k]
        return [(self.doc_ids[idx], float(scores[idx])) for idx in ranked_indices]

    def fit(
        self,
        queries: Sequence[QueryExample],
        kb: Sequence[KBSnippet],
        val_queries: Sequence[QueryExample] | None = None,
        epochs: int = 1,
        batch_size: int = 8,
        learning_rate: float = 2e-5,
    ) -> None:
        """BM25 is non-parametric; fitting re-indexes the knowledge base."""
        self.index(kb)

    def save(self, path: str | Path) -> None:
        """Save BM25 index state."""
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "name": self.name,
                "doc_ids": self.doc_ids,
                "corpus": self.corpus,
                "bm25": self.bm25,
            },
            target_path,
        )

    def load(self, path: str | Path) -> None:
        """Load BM25 index state."""
        target_path = Path(path)
        if not target_path.exists():
            raise FileNotFoundError(f"Index file not found: {target_path}")
        data = joblib.load(target_path)
        self.name = data.get("name", self.name)
        self.doc_ids = data["doc_ids"]
        self.corpus = data["corpus"]
        self.bm25 = data["bm25"]
