"""POST /v1/embed: the pinned embedding model served to kb.search (ADR-0012, App. J)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from contracts.encoder import EmbedResponse
from encoder_service.backend import set_backend
from encoder_service.config import EmbeddingSettings, get_embedding_settings
from encoder_service.embedding import (
    SentenceTransformersEmbedding,
    UnavailableEmbedding,
    build_embedding_backend,
    download_pinned,
    set_embedding,
)
from encoder_service.main import app
from encoder_service.model_backends import BackendConfigError
from fastapi.testclient import TestClient
from retrieval import (
    EmbeddingPinError,
    KBSnippet,
    RemoteEmbeddingAdapter,
)

from .fake_backend import FakeEncoderBackend

MODEL = "org/embedder"
REVISION = "86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d"
WEIGHTS = b"pretend weights"
WEIGHTS_SHA = hashlib.sha256(WEIGHTS).hexdigest()
DIM = 4


class FakeEmbedder:
    """Stands in for SentenceTransformersAdapter: deterministic unit vectors."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self.calls.append(list(texts))
        rows = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vector = np.array([digest[i] + 1 for i in range(DIM)], dtype=np.float64)
            rows.append(vector / np.linalg.norm(vector))
        return np.array(rows, dtype=np.float32)


def settings(**overrides: Any) -> EmbeddingSettings:
    fields: dict[str, Any] = {
        "model": MODEL,
        "revision": REVISION,
        "weights_sha256": WEIGHTS_SHA,
        "max_batch": 8,
        "device": "cpu",
    }
    fields.update(overrides)
    return EmbeddingSettings(**fields)


@pytest.fixture
def hub_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "hub"
    snapshot = cache / "models--org--embedder" / "snapshots" / REVISION
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(WEIGHTS)
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    return cache


@pytest.fixture(autouse=True)
def clean_embedding() -> Generator[None, None, None]:
    set_embedding(None)
    yield
    set_embedding(None)


def fake_backend(**overrides: Any) -> SentenceTransformersEmbedding:
    from encoder.pinning import ResolvedModel

    resolved = ResolvedModel(Path("/models/x"), REVISION, WEIGHTS_SHA)
    return SentenceTransformersEmbedding(
        MODEL, resolved, FakeEmbedder(), overrides.get("max_batch", 8)
    )


# --- The endpoint ---


def test_embed_returns_the_model_identity_and_unit_vectors() -> None:
    set_embedding(fake_backend())
    client = TestClient(app)
    response = client.post("/v1/embed", json={"texts": ["bloquear tarjeta", "card"]})
    assert response.status_code == 200
    body = EmbedResponse.model_validate(response.json())
    assert (body.model_id, body.revision, body.dim) == (MODEL, REVISION, DIM)
    assert len(body.vectors) == 2
    assert np.linalg.norm(body.vectors, axis=1) == pytest.approx([1.0, 1.0], abs=1e-5)
    assert body.vectors[0] != body.vectors[1]


def test_embed_is_deterministic_and_keeps_order() -> None:
    set_embedding(fake_backend())
    client = TestClient(app)
    first = client.post("/v1/embed", json={"texts": ["a", "b"]}).json()["vectors"]
    again = client.post("/v1/embed", json={"texts": ["b", "a"]}).json()["vectors"]
    assert first == list(reversed(again))


def test_embed_without_a_configured_model_says_how_to_configure_it() -> None:
    client = TestClient(app)
    response = client.post("/v1/embed", json={"texts": ["x"]})
    assert response.status_code == 503
    assert "EMBEDDING_MODEL" in response.json()["detail"]


def test_embed_when_the_pinned_model_is_not_cached_says_why() -> None:
    set_embedding(UnavailableEmbedding(MODEL, REVISION, "run make warmup-retrieval"))
    client = TestClient(app)
    response = client.post("/v1/embed", json={"texts": ["x"]})
    assert response.status_code == 503
    assert response.json()["detail"] == "run make warmup-retrieval"


def test_the_batch_limit_is_configuration_and_the_contract_is_a_ceiling() -> None:
    set_embedding(fake_backend(max_batch=2))
    client = TestClient(app)
    assert client.post("/v1/embed", json={"texts": ["a", "b"]}).status_code == 200
    over = client.post("/v1/embed", json={"texts": ["a", "b", "c"]})
    assert over.status_code == 422 and "EMBEDDING_MAX_BATCH" in over.json()["detail"]
    ceiling = client.post("/v1/embed", json={"texts": ["a"] * 257})
    assert ceiling.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"texts": []},
        {"texts": [""]},
        {"texts": ["x" * 4001]},
        {},
        {"texts": ["a"], "x": 1},
    ],
)
def test_invalid_requests_are_422(body: dict[str, Any]) -> None:
    set_embedding(fake_backend())
    assert TestClient(app).post("/v1/embed", json=body).status_code == 422


def test_a_failing_model_is_a_503_and_its_error_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "Zorgblatt-4111111111111111"

    class Boom(FakeEmbedder):
        def embed(self, texts: Sequence[str]) -> np.ndarray:
            if texts != ["probe"]:
                raise RuntimeError(f"bad tensor for {texts!r}")
            return super().embed(texts)

    from encoder.pinning import ResolvedModel

    backend = SentenceTransformersEmbedding(
        MODEL, ResolvedModel(Path("/x"), REVISION, WEIGHTS_SHA), Boom(), 8
    )
    set_embedding(backend)
    with caplog.at_level(logging.DEBUG):
        response = TestClient(app).post("/v1/embed", json={"texts": [secret]})
    assert response.status_code == 503
    assert secret not in response.text and secret not in caplog.text


def test_a_model_returning_non_finite_or_misshapen_vectors_is_a_503() -> None:
    class Bad(FakeEmbedder):
        mode = "ok"

        def embed(self, texts: Sequence[str]) -> np.ndarray:
            out = super().embed(texts)
            if self.mode == "nan":
                out[0, 0] = np.nan
            if self.mode == "short":
                out = out[:-1]
            return out

    from encoder.pinning import ResolvedModel

    embedder = Bad()
    backend = SentenceTransformersEmbedding(
        MODEL, ResolvedModel(Path("/x"), REVISION, WEIGHTS_SHA), embedder, 8
    )
    set_embedding(backend)
    client = TestClient(app)
    for mode in ("nan", "short"):
        embedder.mode = mode
        assert client.post("/v1/embed", json={"texts": ["a", "b"]}).status_code == 503


def test_ready_reports_the_embedding_state() -> None:
    set_backend(FakeEncoderBackend())
    client = TestClient(app)
    import os

    os.environ["ABSTENTION_THRESHOLD"] = "0.5"
    try:
        assert client.get("/ready").json()["embedding"] == {"configured": False}
        set_embedding(fake_backend())
        ready = client.get("/ready").json()["embedding"]
        assert ready == {
            "configured": True,
            "state": "ready",
            "model_id": MODEL,
            "revision": REVISION,
            "dim": DIM,
        }
        set_embedding(UnavailableEmbedding(MODEL, REVISION, "not cached"))
        down = client.get("/ready")
        assert down.status_code == 200  # decisions are still served
        assert down.json()["embedding"]["state"] == "unavailable"
        assert down.json()["embedding"]["reason"] == "not cached"
    finally:
        os.environ.pop("ABSTENTION_THRESHOLD", None)
        set_backend(None)


# --- kb.search's adapter against the real endpoint ---


def snippets() -> list[KBSnippet]:
    return [
        KBSnippet(id="card.es", lang="es", title="Bloqueo", text="bloquear tarjeta"),
        KBSnippet(id="travel.es", lang="es", title="Viaje", text="aviso de viaje"),
    ]


def remote_via(client: TestClient, revision: str = REVISION) -> RemoteEmbeddingAdapter:
    def post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        assert url.endswith("/v1/embed")
        response = client.post("/v1/embed", json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    return RemoteEmbeddingAdapter(
        "http://model-server:8090",
        model_id=MODEL,
        revision=revision,
        post=post,
        batch_size=1,
    )


def test_the_remote_adapter_and_the_endpoint_agree_on_the_wire_contract() -> None:
    set_embedding(fake_backend())
    client = TestClient(app)
    remote = remote_via(client)
    remote.index(snippets())
    # A snippet's own text is its nearest neighbor: the vectors round-tripped intact.
    query = "Bloqueo bloquear tarjeta"
    assert remote.search(query, top_k=1)[0][0] == "card.es"
    assert remote.search(query, top_k=1)[0][1] == pytest.approx(1.0, abs=1e-5)


def test_the_remote_adapter_refuses_an_endpoint_serving_another_revision() -> None:
    set_embedding(fake_backend())
    other = "0" * 40
    with pytest.raises(EmbeddingPinError, match="is pinned"):
        remote_via(TestClient(app), revision=other).index(snippets())


# --- Building the backend: the pin decides ---


def test_a_pinned_cached_model_is_built_and_probed(hub_cache: Path) -> None:
    embedder = FakeEmbedder()
    backend = build_embedding_backend(settings(), load=lambda path: embedder)
    assert isinstance(backend, SentenceTransformersEmbedding)
    assert (backend.model_id, backend.revision, backend.dim) == (MODEL, REVISION, DIM)
    assert backend.weights_sha256 == WEIGHTS_SHA
    assert embedder.calls == [["probe"]]


def test_the_model_is_loaded_from_the_verified_snapshot(hub_cache: Path) -> None:
    loaded: list[Path] = []

    def load(path: Path) -> FakeEmbedder:
        loaded.append(path)
        return FakeEmbedder(path)

    build_embedding_backend(settings(), load=load)
    assert loaded == [hub_cache / "models--org--embedder" / "snapshots" / REVISION]


def test_no_model_configured_means_not_served() -> None:
    assert build_embedding_backend(settings(model=None)) is None


def test_weights_that_differ_from_the_hash_pin_stop_the_service(
    hub_cache: Path,
) -> None:
    with pytest.raises(BackendConfigError, match="not the pinned weights"):
        build_embedding_backend(
            settings(weights_sha256="1" * 64), load=lambda p: FakeEmbedder()
        )


def test_a_hash_pin_is_optional_for_a_hub_model(hub_cache: Path) -> None:
    backend = build_embedding_backend(
        settings(weights_sha256=None), load=lambda p: FakeEmbedder()
    )
    assert isinstance(backend, SentenceTransformersEmbedding)


@pytest.mark.parametrize("revision", [None, "main", "abc123"])
def test_a_missing_or_soft_revision_stops_the_service(
    hub_cache: Path, revision: str | None
) -> None:
    with pytest.raises(BackendConfigError, match="embedding:"):
        build_embedding_backend(
            settings(revision=revision), load=lambda p: FakeEmbedder()
        )


def test_a_pinned_revision_that_is_not_cached_degrades_instead_of_stopping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty"))
    with caplog.at_level(logging.WARNING):
        backend = build_embedding_backend(
            settings(), load=lambda p: pytest.fail("must not load")
        )
    assert isinstance(backend, UnavailableEmbedding) and not backend.is_ready()
    assert REVISION in backend.reason and "make warmup-retrieval" in backend.reason
    assert "not cached" in caplog.text


def test_another_cached_revision_is_not_the_pinned_one(
    hub_cache: Path,
) -> None:
    other = "2" * 40
    backend = build_embedding_backend(
        settings(revision=other), load=lambda p: FakeEmbedder()
    )
    assert isinstance(backend, UnavailableEmbedding)  # only REVISION is cached


def test_a_local_directory_needs_the_hash_pin(tmp_path: Path) -> None:
    model_dir = tmp_path / "fine-tuned"
    model_dir.mkdir()
    (model_dir / "model.safetensors").write_bytes(WEIGHTS)
    ok = build_embedding_backend(
        settings(model=str(model_dir), revision="ft-2026-09-29"),
        load=lambda p: FakeEmbedder(),
    )
    assert (
        isinstance(ok, SentenceTransformersEmbedding) and ok.revision == "ft-2026-09-29"
    )
    with pytest.raises(BackendConfigError, match="set the weights SHA-256 pin"):
        build_embedding_backend(
            settings(model=str(model_dir), revision="ft", weights_sha256=None),
            load=lambda p: FakeEmbedder(),
        )


def test_missing_dependencies_and_load_failures_stop_the_service(
    hub_cache: Path,
) -> None:
    def no_deps(path: Path) -> FakeEmbedder:
        raise BackendConfigError(
            "embedding: dependencies missing; ... `embed` extra ..."
        )

    with pytest.raises(BackendConfigError, match="`embed` extra"):
        build_embedding_backend(settings(), load=no_deps)

    def broken(path: Path) -> FakeEmbedder:
        raise OSError("corrupt weights at /secret/path")

    with pytest.raises(BackendConfigError, match="cannot load 'org/embedder': OSError"):
        build_embedding_backend(settings(), load=broken)


def test_the_default_loader_names_the_extra_when_it_is_missing(
    hub_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "retrieval.adapters.sentence_transformers", None)
    with pytest.raises(BackendConfigError, match="`embed` extra"):
        build_embedding_backend(settings())


def test_cpu_only(hub_cache: Path) -> None:
    with pytest.raises(BackendConfigError, match="ENCODER_DEVICE must be 'cpu'"):
        build_embedding_backend(settings(device="cuda"), load=lambda p: FakeEmbedder())


# --- Configuration ---


def test_settings_from_the_environment() -> None:
    parsed = get_embedding_settings(
        {
            "EMBEDDING_MODEL": " org/embedder ",
            "EMBEDDING_REVISION": REVISION,
            "EMBEDDING_WEIGHTS_SHA256": WEIGHTS_SHA.upper(),
            "EMBEDDING_MAX_BATCH": "16",
        }
    )
    assert parsed == EmbeddingSettings(MODEL, REVISION, WEIGHTS_SHA, 16, "cpu")
    assert get_embedding_settings({}).model is None
    assert get_embedding_settings({}).max_batch == 64


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"EMBEDDING_MAX_BATCH": "many"}, "must be an integer"),
        ({"EMBEDDING_MAX_BATCH": "0"}, "between 1 and 256"),
        ({"EMBEDDING_MAX_BATCH": "257"}, "between 1 and 256"),
        ({"EMBEDDING_WEIGHTS_SHA256": "abc"}, "64 hexadecimal"),
    ],
)
def test_invalid_settings_fail_loudly(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        get_embedding_settings(env)


# --- Through the service lifespan ---


def test_startup_serves_the_pinned_model(
    hub_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL", MODEL)
    monkeypatch.setenv("EMBEDDING_REVISION", REVISION)
    monkeypatch.setenv("EMBEDDING_WEIGHTS_SHA256", WEIGHTS_SHA)
    monkeypatch.setattr(
        "encoder_service.embedding._load_sentence_transformers",
        lambda path: FakeEmbedder(path),
    )
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.5")
    set_backend(FakeEncoderBackend())
    with TestClient(app) as client:
        body = client.post("/v1/embed", json={"texts": ["hola"]}).json()
        assert body["revision"] == REVISION and body["dim"] == DIM
        assert client.get("/ready").json()["embedding"]["state"] == "ready"
    # A stopped service serves nothing.
    assert (
        TestClient(app).post("/v1/embed", json={"texts": ["hola"]}).status_code == 503
    )


def test_startup_stops_on_a_hash_mismatch(
    hub_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL", MODEL)
    monkeypatch.setenv("EMBEDDING_REVISION", REVISION)
    monkeypatch.setenv("EMBEDDING_WEIGHTS_SHA256", "3" * 64)
    with pytest.raises(BackendConfigError, match="not the pinned weights"):
        with TestClient(app):
            pass


def test_startup_survives_a_model_that_is_not_cached_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty"))
    monkeypatch.setenv("EMBEDDING_MODEL", MODEL)
    monkeypatch.setenv("EMBEDDING_REVISION", REVISION)
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.5")
    set_backend(FakeEncoderBackend())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json()["embedding"]["state"] == "unavailable"
        assert client.post("/v1/embed", json={"texts": ["x"]}).status_code == 503


def test_download_pinned_fetches_only_the_pinned_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    calls: list[tuple[Any, ...]] = []
    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = lambda *a, **k: calls.append((a, k))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    download_pinned(settings())
    [(args, kwargs)] = calls
    assert args == (MODEL,) and kwargs["revision"] == REVISION
    assert "onnx/*" in kwargs["ignore_patterns"]
    download_pinned(settings(model=None))
    assert len(calls) == 1  # nothing to fetch
