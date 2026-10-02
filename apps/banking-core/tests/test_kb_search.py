"""Tests for the kb.search service function (2B-3e) on a small fixture KB."""

import hashlib
import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from banking_core.knowledge.config import KbSearchConfig
from banking_core.knowledge.tools import (
    KbSearcher,
    KbSearchUnavailableError,
    execute_kb_search,
)
from contracts.tools.kb_search import KbSearchInput, KbSearchOutput
from pydantic import ValidationError
from retrieval import RemoteEmbeddingAdapter, RetrievalAdapter
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
MODEL_ID = "ibm-granite/granite-embedding-311m-multilingual-r2"


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
    for var in (
        "RETRIEVAL_MODE",
        "RETRIEVAL_TOP_K",
        "EMBEDDING_MODEL",
        "KB_PATH",
        "EMBEDDING_BACKEND",
        "EMBEDDING_DTYPE",
        "EMBEDDING_REVISION",
        "MODEL_SERVER_URL",
        "MODEL_SERVER_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)
    defaults = KbSearchConfig.from_env()
    assert defaults.backend == "vector"
    assert defaults.embedding_dtype == "float32"
    assert defaults.embedding_backend == "remote"  # the model server, not in process
    assert defaults.model_server_url is None and defaults.embedding_revision is None

    monkeypatch.setenv("RETRIEVAL_MODE", "BM25")
    monkeypatch.setenv("RETRIEVAL_TOP_K", "7")
    config = KbSearchConfig.from_env()
    assert (config.backend, config.max_k) == ("bm25", 7)

    monkeypatch.setenv("RETRIEVAL_MODE", "keyword")
    with pytest.raises(ValidationError):
        KbSearchConfig.from_env()


def test_model_server_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_BACKEND", "LOCAL")
    monkeypatch.setenv("EMBEDDING_DTYPE", "BFLOAT16")
    monkeypatch.setenv("EMBEDDING_REVISION", REVISION)
    monkeypatch.setenv("MODEL_SERVER_URL", "http://encoder:8090")
    monkeypatch.setenv("MODEL_SERVER_TIMEOUT_SECONDS", "2.5")
    config = KbSearchConfig.from_env()
    assert config.embedding_backend == "local"
    assert config.embedding_dtype == "bfloat16"
    assert (config.embedding_revision, config.model_server_url) == (
        REVISION,
        "http://encoder:8090",
    )
    assert config.model_server_timeout == 2.5

    monkeypatch.setenv("EMBEDDING_BACKEND", "cloud")
    with pytest.raises(ValidationError):
        KbSearchConfig.from_env()
    monkeypatch.setenv("EMBEDDING_BACKEND", "remote")
    monkeypatch.setenv("EMBEDDING_DTYPE", "int8")
    with pytest.raises(ValidationError):
        KbSearchConfig.from_env()
    monkeypatch.setenv("EMBEDDING_DTYPE", "float32")
    monkeypatch.setenv("MODEL_SERVER_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValidationError):
        KbSearchConfig.from_env()


def test_missing_vector_extra_fails_loudly(
    kb_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "retrieval.adapters.sentence_transformers", None)
    with pytest.raises(KbSearchUnavailableError, match="'vector' extra"):
        KbSearcher(KbSearchConfig(kb_path=kb_path, embedding_backend="local"))


def test_missing_model_fails_loudly_without_bm25_fallback(kb_path: Path) -> None:
    config = KbSearchConfig(
        kb_path=kb_path,
        embedding_backend="local",
        embedding_model="pattern-blue/model-that-is-not-cached",
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
    not _vector_ready(), reason="needs banking-core[vector] and Granite in the HF cache"
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
    """Default config (seed floor 0.80): the top hit is the right topic."""
    searcher = KbSearcher(KbSearchConfig(kb_path=kb_path, embedding_backend="local"))
    out = searcher.search(KbSearchInput(query=query, locale=locale, limit=1))
    assert [r.article_id for r in out.results] == [f"{expected_topic}.{locale}"]


@pytest.mark.skipif(
    not _vector_ready(), reason="needs banking-core[vector] and Granite in the HF cache"
)
def test_vector_falls_back_cross_language_for_a_topic_missing_in_es(
    kb_path: Path,
) -> None:
    searcher = KbSearcher(KbSearchConfig(kb_path=kb_path, embedding_backend="local"))
    out = searcher.search(
        KbSearchInput(query="cómo hago una transferencia pix", locale="es", limit=1)
    )
    assert [r.article_id for r in out.results] == ["pix.01.pt"]


# --- The model server (ADR-0012, Appendix J) ---

REVISION = "86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d"
SERVER_URL = "http://model-server:8090"
DIM = 16


def hashed_embedding(text: str) -> list[float]:
    """Deterministic bag-of-words vectors: texts that share words are close."""
    vector = [0.0] * DIM
    for word in text.lower().split():
        digest = hashlib.sha256(word.encode()).digest()
        vector[digest[0] % DIM] += 1.0 + digest[1] / 255.0
    return vector


class FakeModelServer:
    """A stand-in for POST /v1/embed that counts how often it is asked."""

    def __init__(self, **overrides: Any) -> None:
        self.requests = 0
        self.overrides = overrides

    def __call__(
        self, url: str, payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        self.requests += 1
        response = {
            "model_id": MODEL_ID,
            "revision": REVISION,
            "dim": DIM,
            "vectors": [hashed_embedding(t) for t in payload["texts"]],
        }
        response.update(self.overrides)
        return response


def remote_config(kb_path: Path, **overrides: object) -> KbSearchConfig:
    values: dict[str, object] = {
        "kb_path": kb_path,
        "model_server_url": SERVER_URL,
        "embedding_revision": REVISION,
        "score_floor": 0.0,
    }
    values.update(overrides)
    return KbSearchConfig(**values)  # type: ignore[arg-type]


def remote_searcher(
    kb_path: Path, server: FakeModelServer | None = None, **overrides: object
) -> KbSearcher:
    config = remote_config(kb_path, **overrides)
    adapter = RemoteEmbeddingAdapter(
        SERVER_URL,
        model_id=MODEL_ID,
        revision=REVISION,
        post=server or FakeModelServer(),
    )
    return KbSearcher(config, adapter=adapter)


def test_the_default_backend_is_the_model_server(kb_path: Path) -> None:
    from banking_core.knowledge.tools.kb_search import build_adapter

    adapter = build_adapter(remote_config(kb_path, model_server_timeout=3.0))
    assert isinstance(adapter, RemoteEmbeddingAdapter)
    assert adapter.url == f"{SERVER_URL}/v1/embed"
    assert (adapter.model_id, adapter.revision, adapter.timeout) == (
        MODEL_ID,
        REVISION,
        3.0,
    )


def test_remote_search_finds_the_topic_in_the_customer_language(kb_path: Path) -> None:
    searcher = remote_searcher(kb_path)
    out = searcher.search(
        KbSearchInput(query="bloquear tarjeta robada perdida", locale="es", limit=2)
    )
    assert out.results[0].article_id == "card_block.01.es"
    assert all(r.article_id.endswith(".es") for r in out.results)
    assert all(0.0 <= r.score <= 1.0 for r in out.results)
    assert KbSearchOutput.model_validate_json(out.model_dump_json()) == out


def test_the_index_is_built_once_from_the_model_server_and_queries_go_one_by_one(
    kb_path: Path,
) -> None:
    server = FakeModelServer()
    searcher = remote_searcher(kb_path, server)
    after_index = server.requests
    assert after_index >= 1  # the KB is embedded at startup, in batches
    searcher.search(KbSearchInput(query="aviso de viaje al exterior", locale="es"))
    assert server.requests == after_index + 1
    searcher.search(KbSearchInput(query="bloquear tarjeta", locale="es"))
    assert server.requests == after_index + 2  # each new query is one request


def test_the_same_to_cross_fallback_embeds_the_query_once(kb_path: Path) -> None:
    server = FakeModelServer()
    searcher = remote_searcher(kb_path, server, score_floor=0.99)  # nothing passes SAME
    before = server.requests
    out = searcher.search(
        KbSearchInput(query="cómo hago una transferencia pix", locale="es")
    )
    assert out.results == []
    assert server.requests == before + 1  # SAME and CROSS shared one embedding


def test_remote_hybrid_fuses_bm25_with_the_model_server(kb_path: Path) -> None:
    config = remote_config(kb_path, backend="hybrid")
    adapter = RemoteEmbeddingAdapter(
        SERVER_URL, model_id=MODEL_ID, revision=REVISION, post=FakeModelServer()
    )
    from retrieval import BM25Adapter, HybridAdapter

    searcher = KbSearcher(config, adapter=HybridAdapter(BM25Adapter(), adapter))
    out = searcher.search(KbSearchInput(query="bloquear tarjeta", locale="es", limit=1))
    assert out.results[0].article_id == "card_block.01.es"


def test_the_remote_path_never_imports_the_local_model(
    kb_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The RSS of the embedding model is out of banking-core when nothing imports it."""
    for name in (
        "retrieval.adapters.sentence_transformers",
        "sentence_transformers",
        "torch",
    ):
        monkeypatch.setitem(sys.modules, name, None)
    from banking_core.knowledge.tools.kb_search import build_adapter

    assert isinstance(build_adapter(remote_config(kb_path)), RemoteEmbeddingAdapter)
    searcher = remote_searcher(kb_path)
    assert searcher.search(KbSearchInput(query="viaje", locale="es")).results


def test_the_remote_backend_needs_the_url_and_the_pin(kb_path: Path) -> None:
    with pytest.raises(
        KbSearchUnavailableError, match="MODEL_SERVER_URL and EMBEDDING_REVISION"
    ):
        KbSearcher(KbSearchConfig(kb_path=kb_path))
    with pytest.raises(KbSearchUnavailableError, match="set EMBEDDING_REVISION"):
        KbSearcher(KbSearchConfig(kb_path=kb_path, model_server_url=SERVER_URL))
    with pytest.raises(KbSearchUnavailableError, match="set MODEL_SERVER_URL"):
        KbSearcher(KbSearchConfig(kb_path=kb_path, embedding_revision=REVISION))
    with pytest.raises(KbSearchUnavailableError, match="invalid"):
        KbSearcher(remote_config(kb_path, model_server_url="ftp://encoder"))


def test_another_model_or_revision_makes_kb_search_unavailable(kb_path: Path) -> None:
    for override in ({"revision": "0" * 40}, {"model_id": "other/model"}):
        with pytest.raises(KbSearchUnavailableError, match="is pinned"):
            remote_searcher(kb_path, FakeModelServer(**override))


def test_a_server_swapped_after_startup_fails_the_next_search_not_silently(
    kb_path: Path,
) -> None:
    server = FakeModelServer()
    searcher = remote_searcher(kb_path, server)
    assert searcher.search(KbSearchInput(query="viaje", locale="es")).results
    server.overrides = {"revision": "1" * 40}
    with pytest.raises(KbSearchUnavailableError, match="is pinned"):
        searcher.search(KbSearchInput(query="otra consulta distinta", locale="es"))


def test_an_unreachable_model_server_is_unavailable_never_a_fallback(
    kb_path: Path,
) -> None:
    config = remote_config(
        kb_path, model_server_url="http://127.0.0.1:9", model_server_timeout=1.0
    )
    with pytest.raises(KbSearchUnavailableError, match="unreachable"):
        KbSearcher(config)


def test_a_model_server_that_goes_down_fails_the_search(kb_path: Path) -> None:
    from retrieval import EmbeddingServiceError

    calls = {"n": 0}

    def flaky(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] > 1:  # the index was built by the first call
            raise EmbeddingServiceError(
                "the model server is unreachable (ConnectionError)"
            )
        return FakeModelServer()(url, payload, timeout)

    adapter = RemoteEmbeddingAdapter(
        SERVER_URL, model_id=MODEL_ID, revision=REVISION, post=flaky, batch_size=64
    )
    searcher = KbSearcher(remote_config(kb_path), adapter=adapter)
    with pytest.raises(KbSearchUnavailableError, match="unreachable"):
        searcher.search(KbSearchInput(query="viaje", locale="es"))
