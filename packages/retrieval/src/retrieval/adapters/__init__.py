from typing import TYPE_CHECKING, Any

from retrieval.adapters.bm25 import BM25Adapter
from retrieval.adapters.hybrid import HybridAdapter

if TYPE_CHECKING:
    from retrieval.adapters.sentence_transformers import SentenceTransformersAdapter

__all__ = ["BM25Adapter", "HybridAdapter", "SentenceTransformersAdapter"]


def __getattr__(name: str) -> Any:
    # The dense adapter needs the `vector` extra (torch, sentence-transformers);
    # import it only when asked for, so BM25 works without them.
    if name == "SentenceTransformersAdapter":
        from retrieval.adapters.sentence_transformers import (
            SentenceTransformersAdapter,
        )

        return SentenceTransformersAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
