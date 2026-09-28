import pytest
from retrieval import (
    BM25Adapter,
    HybridAdapter,
    KBSnippet,
    KnowledgeBase,
    Retriever,
    SearchMode,
)

from .fakes import FixedRankingAdapter

TOPICS = {
    "block.01": {
        "es": "Bloqueo de tarjeta robada",
        "pt": "Bloqueio de cartao roubado",
        "en": "Block a stolen card",
    },
    "dispute.01": {
        "es": "Disputa de un cargo no reconocido",
        "pt": "Contestacao de uma compra nao reconhecida",
        "en": "Dispute an unrecognized charge",
    },
}


@pytest.fixture
def kb() -> KnowledgeBase:
    return KnowledgeBase(
        KBSnippet(id=f"{topic}.{lang}", topic_id=topic, lang=lang, title=t, text=t)
        for topic, by_lang in TOPICS.items()
        for lang, t in by_lang.items()
    )


RANKING = [
    "dispute.01.en",
    "block.01.pt",
    "block.01.es",
    "dispute.01.es",
    "block.01.en",
    "dispute.01.pt",
]


def _ids(results: list) -> list[str]:
    return [r.snippet_id for r in results]


def test_same_mode_keeps_only_the_query_language(kb: KnowledgeBase) -> None:
    retriever = Retriever(kb, FixedRankingAdapter(RANKING))
    results = retriever.search("q", lang="es", k=5)
    assert _ids(results) == ["block.01.es", "dispute.01.es"]
    assert [r.rank for r in results] == [1, 2]


def test_cross_mode_excludes_the_query_language(kb: KnowledgeBase) -> None:
    retriever = Retriever(kb, FixedRankingAdapter(RANKING))
    results = retriever.search("q", lang="es", k=3, mode=SearchMode.CROSS)
    assert _ids(results) == ["dispute.01.en", "block.01.pt", "block.01.en"]


def test_any_mode_needs_no_language(kb: KnowledgeBase) -> None:
    retriever = Retriever(kb, FixedRankingAdapter(RANKING))
    assert _ids(retriever.search("q", k=2, mode=SearchMode.ANY)) == RANKING[:2]


def test_filtered_modes_require_a_language(kb: KnowledgeBase) -> None:
    retriever = Retriever(kb, FixedRankingAdapter(RANKING))
    with pytest.raises(ValueError, match="query language"):
        retriever.search("q", mode=SearchMode.CROSS)


@pytest.mark.parametrize("k", [0, -1, 4])
def test_search_rejects_k_outside_configured_cap(kb: KnowledgeBase, k: int) -> None:
    retriever = Retriever(kb, FixedRankingAdapter(RANKING), max_k=3)
    with pytest.raises(ValueError, match="configured max_k"):
        retriever.search("q", k=k, mode=SearchMode.ANY)


def test_search_allows_configured_max_k(kb: KnowledgeBase) -> None:
    retriever = Retriever(kb, FixedRankingAdapter(RANKING), max_k=3)
    assert _ids(retriever.search("q", k=3, mode=SearchMode.ANY)) == RANKING[:3]


def test_search_default_cap_comes_from_the_knowledge_base(
    kb: KnowledgeBase,
) -> None:
    retriever = Retriever(kb, FixedRankingAdapter(RANKING))
    with pytest.raises(ValueError, match="configured max_k"):
        retriever.search("q", k=len(kb) + 1, mode=SearchMode.ANY)


def test_retriever_rejects_nonpositive_max_k(kb: KnowledgeBase) -> None:
    with pytest.raises(ValueError, match="max_k"):
        Retriever(kb, FixedRankingAdapter(RANKING), max_k=0)


def test_bm25_same_language_finds_the_topic(kb: KnowledgeBase) -> None:
    retriever = Retriever(kb, BM25Adapter())
    assert _ids(retriever.search("cartao roubado", lang="pt", k=1)) == ["block.01.pt"]


def test_rrf_fuses_hand_computed_ranks(kb: KnowledgeBase) -> None:
    lexical = FixedRankingAdapter(["a", "b", "c"], name="lex")
    dense = FixedRankingAdapter(["c", "a", "b"], name="dense")
    hybrid = HybridAdapter(lexical, dense, rrf_k=1)
    hybrid.index([KBSnippet(id=i, lang="es", title=i, text=i) for i in ("a", "b", "c")])
    # a: 1/2 + 1/3, c: 1/4 + 1/2, b: 1/3 + 1/4
    ranked = hybrid.search("q", top_k=3)
    assert [doc for doc, _ in ranked] == ["a", "c", "b"]
    assert ranked[0][1] == pytest.approx(1 / 2 + 1 / 3)


def test_rrf_breaks_ties_by_id() -> None:
    hybrid = HybridAdapter(
        FixedRankingAdapter(["b", "a"]), FixedRankingAdapter(["a", "b"]), rrf_k=60
    )
    hybrid.index([KBSnippet(id=i, lang="es", title=i, text=i) for i in ("a", "b")])
    assert [doc for doc, _ in hybrid.search("q")] == ["a", "b"]


def test_rrf_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="rrf_k"):
        HybridAdapter(FixedRankingAdapter([]), FixedRankingAdapter([]), rrf_k=0)


def test_hybrid_fit_fits_both_backends(kb: KnowledgeBase) -> None:
    lexical, dense = FixedRankingAdapter(RANKING), FixedRankingAdapter(RANKING)
    HybridAdapter(lexical, dense).fit([], list(kb.snippets))
    assert lexical.fitted and dense.fitted
