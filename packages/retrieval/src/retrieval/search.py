"""Language-aware search over a knowledge base."""

from __future__ import annotations

from enum import StrEnum

from retrieval.base import RetrievalAdapter
from retrieval.kb import KnowledgeBase
from retrieval.models import SearchResult


class SearchMode(StrEnum):
    SAME = "same"  # only snippets in the query's language
    CROSS = "cross"  # only snippets in the other languages
    ANY = "any"  # every snippet


class Retriever:
    """Wraps an indexed adapter and applies the language filter.

    The adapter ranks the whole KB once and the filter is applied to that
    ranking, so a single index serves every mode. For dense scores this is
    identical to searching a per-language index; for BM25 the IDF statistics
    come from the whole multilingual KB.
    """

    def __init__(self, kb: KnowledgeBase, adapter: RetrievalAdapter) -> None:
        self.kb = kb
        self.adapter = adapter
        self.adapter.index(list(kb.snippets))

    def search(
        self,
        query: str,
        lang: str | None = None,
        k: int = 5,
        mode: SearchMode = SearchMode.SAME,
    ) -> list[SearchResult]:
        if mode is not SearchMode.ANY and lang is None:
            raise ValueError(f"mode '{mode}' needs the query language")
        ranking = self.adapter.search(query, top_k=len(self.kb))
        results: list[SearchResult] = []
        for doc_id, score in ranking:
            doc_lang = self.kb.lang_of(doc_id)
            if mode is SearchMode.SAME and doc_lang != lang:
                continue
            if mode is SearchMode.CROSS and doc_lang == lang:
                continue
            results.append(
                SearchResult(snippet_id=doc_id, score=score, rank=len(results) + 1)
            )
            if len(results) == k:
                break
        return results
