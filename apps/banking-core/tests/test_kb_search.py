"""Tests for the kb.search service function (2B-3e) on a small fixture KB."""

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from banking_core.knowledge.config import KbSearchConfig
from banking_core.knowledge.tools import (
    KbSearcher,
    KbSearchUnavailableError,
    execute_kb_search,
)
from contracts.tools.kb_search import KbSearchInput, KbSearchOutput
from pydantic import ValidationError
from retrieval import RetrievalAdapter
from retrieval.models import KBSnippet, QueryExample

SNIPPETS = [
    (
        "card_block.01",
        "es",
        "Bloqueo de tarjeta",
        "Para bloquear su tarjeta robada o perdida, "
        "confirme su identidad con un código OTP.",
    ),
    (
        "card_block.01",
        "pt",
        "Bloqueio de cartão",
        "Para bloquear seu cartão roubado ou perdido, "
        "confirme sua identidade com um código OTP.",
    ),
    (
        "card_block.01",
        "en",
        "Card block",
        "To block your stolen or lost card, confirm your identity with an OTP code.",
    ),
    (
        "travel.01",
        "es",
        "Aviso de viaje",
        "Informe sus fechas de viaje al exterior para evitar rechazos de compras.",
    ),
    (
        "travel.01",
        "pt",
        "Aviso de viagem",
        "Informe as datas da sua viagem ao exterior para evitar recusas de compras.",
    ),
    (
        "travel.01",
        "en",
        "Travel notice",
        "Tell us your travel dates abroad to avoid declined purchases.",
    ),
    (
        "pix.01",
        "pt",
        "Transferências Pix",
        "O Pix permite transferências instantâneas "
        "a qualquer hora usando uma chave Pix.",
    ),
]
MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@pytest.fixture
def kb_path(tmp_path: Path) -> Path:
    path = tmp_path / "snippets.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": f"{t}.{lang}",
                    "topic_id": t,
                    "lang": lang,
                    "title": ti,
                    "text": tx,
                }
            )
            for t, lang, ti, tx in SNIPPETS
        ),
        encoding="utf-8",
    )
    return path


def bm25_searcher(kb_path: Path, **overrides: object) -> KbSearcher:
    config = KbSearchConfig(kb_path=kb_path, backend="bm25", **overrides)
    return KbSearcher(config)


class FixedScores(RetrievalAdapter):
    """Adapter returning preset scores, to pin the SAME -> CROSS rule."""

    name = "fixed"

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def index(self, kb: Sequence[KBSnippet]) -> None:
        self.ids = [s.id for s in kb]

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        ranked = sorted(self.ids, key=lambda i: -self.scores.get(i, 0.0))
        return [(i, self.scores.get(i, 0.0)) for i in ranked[:top_k]]

    def fit(
        self,
        queries: Sequence[QueryExample],
        kb: Sequence[KBSnippet],
        val_queries: Sequence[QueryExample] | None = None,
        epochs: int = 1,
        batch_size: int = 8,
        learning_rate: float = 2e-5,
    ) -> None:
        raise NotImplementedError

    def save(self, path: str | Path) -> None:
        raise NotImplementedError

    def load(self, path: str | Path) -> None:
        raise NotImplementedError


@pytest.mark.parametrize(
    ("locale", "query", "expected"),
    [
        ("es", "bloquear tarjeta robada", "card_block.01.es"),
        ("pt", "bloquear cartão roubado", "card_block.01.pt"),
        ("en", "block my stolen card", "card_block.01.en"),
        ("es-CO", "aviso de viaje al exterior", "travel.01.es"),
    ],
)
def test_bm25_hits_the_topic_in_the_customer_language(
    kb_path: Path, locale: str, query: str, expected: str
) -> None:
    out = execute_kb_search(
        KbSearchInput(query=query, locale=locale), bm25_searcher(kb_path)
    )
    assert out.results[0].article_id == expected
    assert out.results[0].category == expected.split(".")[0]
    assert all(r.article_id.endswith("." + locale[:2]) for r in out.results)
    assert KbSearchOutput.model_validate_json(out.model_dump_json()) == out


def test_same_language_first_then_cross_below_the_floor(kb_path: Path) -> None:
    config = KbSearchConfig(kb_path=kb_path, score_floor=0.5)
    weak_same = FixedScores({"travel.01.es": 0.2, "pix.01.pt": 0.9})
    out = KbSearcher(config, adapter=weak_same).search(
        KbSearchInput(query="transferencia pix", locale="es")
    )
    assert [r.article_id for r in out.results] == ["pix.01.pt"]
    assert out.results[0].score == 0.9

    strong_same = FixedScores({"travel.01.es": 0.6, "pix.01.pt": 0.9})
    out = KbSearcher(config, adapter=strong_same).search(
        KbSearchInput(query="viaje", locale="es")
    )
    assert [r.article_id for r in out.results] == ["travel.01.es"]


def test_nothing_above_the_floor_returns_no_results(kb_path: Path) -> None:
    config = KbSearchConfig(kb_path=kb_path, score_floor=0.5)
    out = KbSearcher(config, adapter=FixedScores({})).search(
        KbSearchInput(query="hipoteca", locale="en")
    )
    assert out.results == []


def test_k_is_bounded_by_the_request_and_the_config(kb_path: Path) -> None:
    config = KbSearchConfig(kb_path=kb_path, max_k=2, score_floor=0.0)
    scores = {f"{t}.{lang}": 0.8 for t, lang, *_ in SNIPPETS}
    searcher = KbSearcher(config, adapter=FixedScores(scores))

    assert (
        len(searcher.search(KbSearchInput(query="x y", locale="pt", limit=20)).results)
        == 2
    )
    assert (
        len(searcher.search(KbSearchInput(query="x y", locale="pt", limit=1)).results)
        == 1
    )
    with pytest.raises(ValidationError):
        KbSearchConfig(max_k=21)
    with pytest.raises(ValidationError):
        KbSearchConfig(max_k=0)


def test_kb_smaller_than_the_configured_k_returns_what_it_has(tmp_path: Path) -> None:
    path = tmp_path / "small.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "card_block.01.es",
                "topic_id": "card_block.01",
                "lang": "es",
                "title": "Bloqueo de tarjeta",
                "text": "Para bloquear su tarjeta robada, confirme su identidad.",
            }
        ),
        encoding="utf-8",
    )
    searcher = bm25_searcher(path, max_k=5, score_floor=0.0)

    out = searcher.search(KbSearchInput(query="bloquear tarjeta", locale="es", limit=5))

    assert [r.article_id for r in out.results] == ["card_block.01.es"]


def test_empty_kb_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(KbSearchUnavailableError, match="no snippets"):
        bm25_searcher(path)


def test_config_from_env_defaults_to_vector_and_validates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("RETRIEVAL_MODE", "RETRIEVAL_TOP_K", "EMBEDDING_MODEL", "KB_PATH"):
        monkeypatch.delenv(var, raising=False)
    assert KbSearchConfig.from_env().backend == "vector"

    monkeypatch.setenv("RETRIEVAL_MODE", "BM25")
    monkeypatch.setenv("RETRIEVAL_TOP_K", "7")
    config = KbSearchConfig.from_env()
    assert (config.backend, config.max_k) == ("bm25", 7)

    monkeypatch.setenv("RETRIEVAL_MODE", "keyword")
    with pytest.raises(ValidationError):
        KbSearchConfig.from_env()


def test_missing_vector_extra_fails_loudly(
    kb_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "retrieval.adapters.sentence_transformers", None)
    with pytest.raises(KbSearchUnavailableError, match="'vector' extra"):
        KbSearcher(KbSearchConfig(kb_path=kb_path))


def test_missing_model_fails_loudly_without_bm25_fallback(kb_path: Path) -> None:
    config = KbSearchConfig(
        kb_path=kb_path, embedding_model="pattern-blue/model-that-is-not-cached"
    )
    with pytest.raises(KbSearchUnavailableError):
        KbSearcher(config)


def test_missing_kb_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(KbSearchUnavailableError, match="knowledge base"):
        bm25_searcher(tmp_path / "absent.jsonl")


def _vector_ready() -> bool:
    if importlib.util.find_spec("sentence_transformers") is None:
        return False
    from huggingface_hub import snapshot_download

    try:
        snapshot_download(MODEL_ID, local_files_only=True)
    except Exception:
        return False
    return True


@pytest.mark.skipif(
    not _vector_ready(), reason="needs banking-core[vector] and MiniLM in the HF cache"
)
@pytest.mark.parametrize(
    ("locale", "query", "expected_topic"),
    [
        ("es", "me robaron la tarjeta, quiero bloquearla", "card_block.01"),
        ("pt", "aviso de viagem ao exterior", "travel.01"),
        ("en", "someone stole my card", "card_block.01"),
    ],
)
def test_vector_hits_the_topic_in_each_language(
    kb_path: Path, locale: str, query: str, expected_topic: str
) -> None:
    """Default config (seed floor 0.3): the top hit is the right topic."""
    searcher = KbSearcher(KbSearchConfig(kb_path=kb_path))
    out = searcher.search(KbSearchInput(query=query, locale=locale, limit=1))
    assert [r.article_id for r in out.results] == [f"{expected_topic}.{locale}"]


@pytest.mark.skipif(
    not _vector_ready(), reason="needs banking-core[vector] and MiniLM in the HF cache"
)
def test_vector_falls_back_cross_language_for_a_topic_missing_in_es(
    kb_path: Path,
) -> None:
    searcher = KbSearcher(KbSearchConfig(kb_path=kb_path))
    out = searcher.search(
        KbSearchInput(query="cómo hago una transferencia pix", locale="es", limit=1)
    )
    assert [r.article_id for r in out.results] == ["pix.01.pt"]
