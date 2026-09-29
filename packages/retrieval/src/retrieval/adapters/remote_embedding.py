"""Dense retrieval whose embeddings come from the model server (ADR-0012, App. J).

The knowledge base index (about 120 snippets) is held in this process's memory,
built from vectors that ``POST /v1/embed`` returned; each query is embedded by the
model server per call. The similarity is the one ``SentenceTransformersAdapter``
uses (unit vectors, dot product), so the ranking is the same.

The model server is a dependency this process does not fully trust: it can be down,
swapped for another model, or wrong. So every response is checked:

* ``model_id`` and ``revision`` must equal the pin this adapter was built with
  (``EmbeddingPinError``). A mismatch never becomes a silent comparison of vectors
  from two models.
* the count, the dimension (fixed by the first response) and finiteness of the
  vectors, and each vector is re-normalized (a zero vector is refused), so a bad
  norm cannot inflate a score.

A compromised server can still return *plausible* wrong vectors and so make a wrong
public snippet rank first. That is declared in ``docs/limitations.md``; nothing
here executes or authorizes anything from the response.

Errors carry a status or a class name, never the response body or the text sent.
No dependency beyond numpy: the HTTP call is the standard library's.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from retrieval.base import RetrievalAdapter
from retrieval.models import KBSnippet, QueryExample

# A batch of 256 vectors of 4096 float64 is well under this; more is not a vector.
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_DETAIL_CHARS = 200

Post = Callable[[str, dict[str, Any], float], dict[str, Any]]


class EmbeddingServiceError(RuntimeError):
    """The model server did not give a usable answer. The message says why."""


class EmbeddingPinError(EmbeddingServiceError):
    """The model server serves another model or revision than the pinned one."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """POST JSON with the standard library: no redirects, a size cap, terse errors."""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise EmbeddingServiceError("the model server URL must be http or https")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise EmbeddingServiceError(_http_message(exc)) from exc
    except (urllib.error.URLError, OSError) as exc:
        # TimeoutError and ConnectionError are OSErrors; the reason is a class name.
        reason = getattr(exc, "reason", exc)
        raise EmbeddingServiceError(
            f"the model server is unreachable ({type(reason).__name__})"
        ) from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise EmbeddingServiceError("the model server's answer is too large")
    try:
        decoded = json.loads(body)
    except ValueError as exc:
        raise EmbeddingServiceError("the model server sent invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise EmbeddingServiceError("the model server sent an unexpected answer")
    return decoded


def _http_message(exc: urllib.error.HTTPError) -> str:
    """'HTTP 503: <reason>' for a 503, whose detail is ours; a bare status otherwise
    (a 422 body can echo the input)."""
    if exc.code != 503:
        return f"the model server answered HTTP {exc.code}"
    try:
        detail = json.loads(exc.read(2000)).get("detail")
    except (ValueError, AttributeError, OSError):
        detail = None
    if isinstance(detail, str) and detail:
        return f"the model server is not ready (HTTP 503): {detail[:_MAX_DETAIL_CHARS]}"
    return "the model server is not ready (HTTP 503)"


class RemoteEmbeddingAdapter(RetrievalAdapter):
    """Dense retrieval over vectors from the model server's ``POST /v1/embed``."""

    def __init__(
        self,
        base_url: str,
        *,
        model_id: str,
        revision: str,
        timeout: float = 10.0,
        batch_size: int = 32,
        name: str | None = None,
        post: Post = post_json,
    ) -> None:
        if urllib.parse.urlsplit(base_url).scheme not in ("http", "https"):
            raise ValueError("the model server URL must be http or https")
        if not model_id or not revision:
            raise ValueError("model_id and revision are the pin: both are required")
        if batch_size < 1 or timeout <= 0:
            raise ValueError("batch_size must be at least 1 and timeout positive")
        self.url = f"{base_url.rstrip('/')}/v1/embed"
        self.model_id = model_id
        self.revision = revision
        self.timeout = timeout
        self.batch_size = batch_size
        self.name = name or f"remote:{model_id.split('/')[-1]}"
        self._post = post
        self.dim: int | None = None
        self.doc_ids: list[str] = []
        self.corpus_embeddings: np.ndarray | None = None

    # -- embeddings --

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Unit-length float32 vectors, one row per text, from the pinned model."""
        if not texts:
            return np.empty((0, self.dim or 0), dtype=np.float32)
        batches = [
            self._embed_batch(list(texts[start : start + self.batch_size]))
            for start in range(0, len(texts), self.batch_size)
        ]
        return np.vstack(batches)

    def _embed_batch(self, batch: list[str]) -> np.ndarray:
        payload = self._post(self.url, {"texts": batch}, self.timeout)
        self._check_identity(payload)
        vectors = payload.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != len(batch):
            raise EmbeddingServiceError(
                "the model server returned a different number of vectors than texts"
            )
        try:
            matrix = np.asarray(vectors, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise EmbeddingServiceError(
                "the model server sent malformed vectors"
            ) from exc
        if matrix.ndim != 2 or matrix.shape[1] < 1:
            raise EmbeddingServiceError("the model server sent malformed vectors")
        dim = int(matrix.shape[1])
        if payload.get("dim") != dim:
            raise EmbeddingServiceError(
                "the vectors do not have the dimension announced"
            )
        if self.dim is None:
            self.dim = dim
        elif self.dim != dim:
            raise EmbeddingServiceError(
                f"the model server changed the embedding dim ({self.dim} -> {dim})"
            )
        if not np.isfinite(matrix).all():
            raise EmbeddingServiceError("the model server sent a non-finite vector")
        norms = np.linalg.norm(matrix, axis=1)
        if not (norms > 0.0).all() or not all(math.isfinite(n) for n in norms):
            raise EmbeddingServiceError("the model server sent a zero vector")
        return (matrix / norms[:, None]).astype(np.float32)

    def _check_identity(self, payload: dict[str, Any]) -> None:
        got_model, got_revision = payload.get("model_id"), payload.get("revision")
        if got_model != self.model_id or got_revision != self.revision:
            raise EmbeddingPinError(
                f"the model server serves {got_model!r} at {got_revision!r}, "
                f"but {self.model_id!r} at {self.revision!r} is pinned"
            )

    # -- RetrievalAdapter --

    def index(self, kb: Sequence[KBSnippet]) -> None:
        """Embed the knowledge base once, through the model server."""
        self.doc_ids = [s.id for s in kb]
        texts = [f"{s.title} {s.text}" for s in kb]
        self.corpus_embeddings = self.embed(texts) if texts else None

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Cosine similarity of the query (embedded per call) against the index."""
        if self.corpus_embeddings is None or not self.doc_ids:
            return []
        query_embedding = self.embed([query])[0]
        scores = np.dot(self.corpus_embeddings, query_embedding)
        ranked = np.argsort(scores)[::-1][:top_k]
        return [(self.doc_ids[i], float(scores[i])) for i in ranked]

    def fit(
        self,
        queries: Sequence[QueryExample],
        kb: Sequence[KBSnippet],
        val_queries: Sequence[QueryExample] | None = None,
        epochs: int = 1,
        batch_size: int = 8,
        learning_rate: float = 2e-5,
    ) -> None:
        raise NotImplementedError(
            "the remote embedding adapter serves a pinned model; fine-tune it offline "
            "with SentenceTransformersAdapter and pin the new revision"
        )

    def save(self, path: str | Path) -> None:
        raise NotImplementedError("the remote embedding adapter has no local state")

    def load(self, path: str | Path) -> None:
        raise NotImplementedError("the remote embedding adapter has no local state")
