"""The remote embedding adapter: same ranking as a local one, and it refuses a model
server that is down, swapped or wrong (ADR-0012, Appendix J)."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections.abc import Callable, Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import numpy as np
import pytest
from retrieval import (
    EmbeddingPinError,
    EmbeddingServiceError,
    KBSnippet,
    KnowledgeBase,
    RemoteEmbeddingAdapter,
    Retriever,
    SearchMode,
)
from retrieval.adapters.remote_embedding import MAX_RESPONSE_BYTES, post_json

MODEL = "org/model"
REVISION = "86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d"
DIM = 16
URL = "http://model-server:8090"


def hashed_embedding(text: str) -> list[float]:
    """A deterministic bag-of-words embedding: shared words share a positive dot."""
    vector = [0.0] * DIM
    for word in text.lower().split():
        digest = hashlib.sha256(word.encode()).digest()
        vector[digest[0] % DIM] += 1.0 + digest[1] / 255.0
    return vector


class FakeModelServer:
    """Stands in for POST /v1/embed; records every batch it was asked for."""

    def __init__(self, **overrides: Any) -> None:
        self.calls: list[list[str]] = []
        self.overrides = overrides

    def __call__(
        self, url: str, payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        assert url == f"{URL}/v1/embed"
        texts = payload["texts"]
        self.calls.append(texts)
        vectors = [hashed_embedding(t) for t in texts]
        response = {
            "model_id": MODEL,
            "revision": REVISION,
            "dim": DIM,
            "vectors": vectors,
        }
        response.update(self.overrides)
        return response


def adapter(
    server: Callable[..., Any] | None = None, **kwargs: Any
) -> RemoteEmbeddingAdapter:
    return RemoteEmbeddingAdapter(
        URL,
        model_id=MODEL,
        revision=REVISION,
        post=server or FakeModelServer(),
        **kwargs,
    )


def snippets() -> list[KBSnippet]:
    rows = [
        ("card.es", "es", "Bloqueo de tarjeta", "bloquear tarjeta robada perdida"),
        ("card.en", "en", "Card block", "block stolen lost card"),
        ("travel.es", "es", "Aviso de viaje", "viaje exterior fechas compras"),
    ]
    return [KBSnippet(id=i, lang=lang, title=t, text=x) for i, lang, t, x in rows]


# --- Ranking ---


def test_the_ranking_matches_a_local_dense_search_over_the_same_vectors() -> None:
    remote = adapter()
    remote.index(snippets())
    ranking = remote.search("bloquear tarjeta", top_k=3)
    assert [doc for doc, _ in ranking][0] == "card.es"
    assert all(-1.0 <= score <= 1.0 + 1e-6 for _, score in ranking)

    # The same computation with plain numpy, as SentenceTransformersAdapter does it.
    docs = np.array(
        [hashed_embedding(f"{s.title} {s.text}") for s in snippets()], dtype=np.float32
    )
    docs /= np.linalg.norm(docs, axis=1, keepdims=True)
    query = np.array(hashed_embedding("bloquear tarjeta"), dtype=np.float32)
    query /= np.linalg.norm(query)
    expected = np.argsort(np.dot(docs, query))[::-1]
    assert [doc for doc, _ in ranking] == [snippets()[i].id for i in expected]


def test_it_plugs_into_the_retriever_with_the_language_filter() -> None:
    kb = KnowledgeBase(snippets())
    retriever = Retriever(kb, adapter())
    same = retriever.search("bloquear tarjeta", lang="es", k=3, mode=SearchMode.SAME)
    assert {hit.snippet_id for hit in same} == {"card.es", "travel.es"}
    cross = retriever.search("bloquear tarjeta", lang="es", k=3, mode=SearchMode.CROSS)
    assert [hit.snippet_id for hit in cross] == ["card.en"]


def test_the_index_is_built_once_and_each_query_is_one_request() -> None:
    server = FakeModelServer()
    remote = adapter(server, batch_size=2)
    remote.index(snippets())
    assert [len(batch) for batch in server.calls] == [2, 1]  # batched
    remote.search("viaje", top_k=1)
    remote.search("tarjeta", top_k=1)
    assert [len(batch) for batch in server.calls[2:]] == [1, 1]
    assert remote.dim == DIM


def test_an_empty_knowledge_base_searches_to_nothing_without_a_request() -> None:
    server = FakeModelServer()
    remote = adapter(server)
    remote.index([])
    assert remote.search("x") == [] and server.calls == []


def test_vectors_are_renormalized_so_a_large_norm_cannot_inflate_a_score() -> None:
    class Loud(FakeModelServer):
        def __call__(
            self, url: str, payload: dict[str, Any], timeout: float
        ) -> dict[str, Any]:
            response = super().__call__(url, payload, timeout)
            response["vectors"] = [
                [v * 1000.0 for v in vec] for vec in response["vectors"]
            ]
            return response

    remote = adapter(Loud())
    remote.index(snippets())
    assert all(score <= 1.0 + 1e-6 for _, score in remote.search("tarjeta", top_k=3))
    norms = np.linalg.norm(remote.embed(["a b c"]), axis=1)
    assert norms == pytest.approx([1.0], abs=1e-6)


# --- The pin ---


@pytest.mark.parametrize(
    "override",
    [
        {"model_id": "other/model"},
        {"revision": "0" * 40},
        {"model_id": None},
        {"revision": None},
    ],
)
def test_another_model_or_revision_is_refused_never_compared(
    override: dict[str, Any],
) -> None:
    remote = adapter(FakeModelServer(**override))
    with pytest.raises(EmbeddingPinError, match="is pinned"):
        remote.index(snippets())


def test_a_server_swapped_after_the_index_was_built_fails_the_next_query() -> None:
    server = FakeModelServer()
    remote = adapter(server)
    remote.index(snippets())
    server.overrides = {"revision": "1" * 40}
    with pytest.raises(EmbeddingPinError):
        remote.search("tarjeta")


def test_the_pin_is_required_to_build_the_adapter() -> None:
    with pytest.raises(ValueError, match="the pin"):
        RemoteEmbeddingAdapter(URL, model_id="", revision=REVISION)
    with pytest.raises(ValueError, match="the pin"):
        RemoteEmbeddingAdapter(URL, model_id=MODEL, revision="")
    with pytest.raises(ValueError, match="http or https"):
        RemoteEmbeddingAdapter("file:///etc/passwd", model_id=MODEL, revision=REVISION)


# --- Bad answers ---


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"vectors": []}, "different number of vectors"),
        ({"vectors": "nope"}, "different number of vectors"),
        ({"vectors": [[1.0, 2.0]] * 3}, "dimension announced"),
        ({"dim": DIM + 1}, "dimension announced"),
        ({"vectors": [[float("nan")] + [0.0] * (DIM - 1)] * 3}, "non-finite"),
        ({"vectors": [[float("inf")] + [0.0] * (DIM - 1)] * 3}, "non-finite"),
        ({"vectors": [[0.0] * DIM] * 3}, "zero vector"),
        ({"vectors": [["a"] * DIM] * 3}, "malformed vectors"),
        ({"vectors": [[[1.0]] * DIM] * 3}, "malformed vectors"),
    ],
)
def test_a_malformed_answer_is_refused(override: dict[str, Any], message: str) -> None:
    remote = adapter(FakeModelServer(**override))
    with pytest.raises(EmbeddingServiceError, match=message):
        remote.index(snippets())


def test_the_dimension_cannot_change_between_answers() -> None:
    server = FakeModelServer()
    remote = adapter(server)
    remote.index(snippets())
    server.overrides = {
        "dim": 4,
        "vectors": [[1.0, 0.0, 0.0, 0.0]],
    }
    with pytest.raises(EmbeddingServiceError, match="changed the embedding dim"):
        remote.search("tarjeta")


def test_errors_never_carry_the_text() -> None:
    secret = "Zorgblatt-4111111111111111"
    remote = adapter(FakeModelServer(vectors=[]))
    with pytest.raises(EmbeddingServiceError) as info:
        remote.embed([secret])
    assert secret not in str(info.value)


def test_a_remote_adapter_has_no_local_state() -> None:
    remote = adapter()
    with pytest.raises(NotImplementedError):
        remote.fit([], [])
    with pytest.raises(NotImplementedError):
        remote.save("x")
    with pytest.raises(NotImplementedError):
        remote.load("x")


# --- post_json over real HTTP ---


class Handler(BaseHTTPRequestHandler):
    """A tiny model server whose behavior the test selects by path."""

    def log_message(self, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        route = self.path
        if route == "/ok/v1/embed":
            self._send(200, {"echo": body, "vectors": [[1.0]]})
        elif route == "/503/v1/embed":
            self._send(503, {"detail": "embedding model is not in the local cache"})
        elif route == "/422/v1/embed":
            self._send(422, {"detail": [{"input": body["texts"][0]}]})
        elif route == "/redirect/v1/embed":
            self.send_response(302)
            self.send_header("Location", "/ok/v1/embed")
            self.end_headers()
        elif route == "/html/v1/embed":
            self._raw(200, b"<html>not json</html>")
        elif route == "/list/v1/embed":
            self._raw(200, b"[1, 2]")
        elif route == "/huge/v1/embed":
            self._raw(200, b" " * (MAX_RESPONSE_BYTES + 10))
        elif route == "/slow/v1/embed":
            time.sleep(1.0)
            self._send(200, {})
        else:
            self._send(404, {})

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        self._raw(status, json.dumps(payload).encode())

    def _raw(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server_url() -> Generator[str, None, None]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_post_json_round_trips(server_url: str) -> None:
    answer = post_json(f"{server_url}/ok/v1/embed", {"texts": ["a"]}, 5.0)
    assert answer["echo"] == {"texts": ["a"]}


def test_a_503_carries_the_servers_reason(server_url: str) -> None:
    with pytest.raises(
        EmbeddingServiceError, match="not ready.*not in the local cache"
    ):
        post_json(f"{server_url}/503/v1/embed", {"texts": ["a"]}, 5.0)


def test_other_http_errors_report_the_status_only(server_url: str) -> None:
    """A 422 body echoes the input; the error must not."""
    with pytest.raises(EmbeddingServiceError) as info:
        post_json(f"{server_url}/422/v1/embed", {"texts": ["Zorgblatt-4111"]}, 5.0)
    assert "422" in str(info.value) and "Zorgblatt" not in str(info.value)


def test_redirects_are_not_followed(server_url: str) -> None:
    with pytest.raises(EmbeddingServiceError, match="HTTP 302"):
        post_json(f"{server_url}/redirect/v1/embed", {"texts": ["a"]}, 5.0)


@pytest.mark.parametrize(
    ("route", "message"),
    [
        ("html", "invalid JSON"),
        ("list", "unexpected answer"),
        ("huge", "too large"),
    ],
)
def test_unusable_bodies_are_refused(server_url: str, route: str, message: str) -> None:
    with pytest.raises(EmbeddingServiceError, match=message):
        post_json(f"{server_url}/{route}/v1/embed", {"texts": ["a"]}, 5.0)


def test_a_slow_server_times_out(server_url: str) -> None:
    started = time.monotonic()
    with pytest.raises(EmbeddingServiceError, match="unreachable"):
        post_json(f"{server_url}/slow/v1/embed", {"texts": ["a"]}, 0.2)
    assert time.monotonic() - started < 0.9


def test_a_closed_port_is_unreachable() -> None:
    with pytest.raises(EmbeddingServiceError, match="unreachable"):
        post_json("http://127.0.0.1:9/v1/embed", {"texts": ["a"]}, 1.0)


def test_only_http_urls_are_used() -> None:
    with pytest.raises(EmbeddingServiceError, match="http or https"):
        post_json("file:///etc/passwd", {"texts": ["a"]}, 1.0)


def test_the_adapter_works_over_real_http(server_url: str) -> None:
    class Echo(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            vectors = [hashed_embedding(t) for t in body["texts"]]
            payload = json.dumps(
                {
                    "model_id": MODEL,
                    "revision": REVISION,
                    "dim": DIM,
                    "vectors": vectors,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    embed_server = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=embed_server.serve_forever, daemon=True).start()
    try:
        remote = RemoteEmbeddingAdapter(
            f"http://127.0.0.1:{embed_server.server_address[1]}",
            model_id=MODEL,
            revision=REVISION,
        )
        remote.index(snippets())
        assert remote.search("bloquear tarjeta", top_k=1)[0][0] == "card.es"
        assert not math.isnan(remote.search("viaje", top_k=1)[0][1])
    finally:
        embed_server.shutdown()
