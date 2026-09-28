from typing import TYPE_CHECKING, Any

from retrieval.adapters import BM25Adapter, HybridAdapter
from retrieval.base import RetrievalAdapter
from retrieval.kb import DEFAULT_KB_PATH, KBValidationError, KnowledgeBase
from retrieval.models import KBSnippet, QueryExample, SearchResult
from retrieval.search import Retriever, SearchMode

if TYPE_CHECKING:
    from retrieval.adapters.sentence_transformers import SentenceTransformersAdapter

__all__ = [
    "DEFAULT_KB_PATH",
    "BM25Adapter",
    "HybridAdapter",
    "KBSnippet",
    "KBValidationError",
    "KnowledgeBase",
    "QueryExample",
    "RetrievalAdapter",
    "Retriever",
    "SearchMode",
    "SearchResult",
    "SentenceTransformersAdapter",
]


def __getattr__(name: str) -> Any:
    # Lazy: needs the `vector` extra (see retrieval.adapters).
    if name == "SentenceTransformersAdapter":
        from retrieval.adapters import SentenceTransformersAdapter

        return SentenceTransformersAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
