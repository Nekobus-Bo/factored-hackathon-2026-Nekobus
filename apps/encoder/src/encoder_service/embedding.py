"""The embedding model served by POST /v1/embed (ADR-0012, Appendix J).

The model is pinned (``encoder.pinning``): a hub id needs a full commit that is in
the local cache, a directory needs its weights SHA-256. It is loaded through the
retrieval package's ``SentenceTransformersAdapter``, so the vectors are the ones an
in-process ``kb.search`` computed before this moved to the model server.

Startup failure classes:

* configured with an invalid or missing pin, weights that do not match the pin, or
  a missing dependency: ``BackendConfigError``, the service does not start;
* a pinned model that is simply not in the cache yet (no network on the first run):
  the service starts, serves decisions, and answers /v1/embed with 503 and the
  reason. It never serves an unpinned model.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from encoder.pinning import (
    ModelNotCachedError,
    PinError,
    ResolvedModel,
    resolve_pinned_model,
)

from encoder_service.backend import ModelUnavailableError
from encoder_service.config import EmbeddingSettings
from encoder_service.model_backends import BackendConfigError

logger = logging.getLogger(__name__)

# Sent once at startup to learn the dimension. Not customer text.
_PROBE_TEXT = "probe"
# Formats the loader never reads; a warmup skips them (the repo can hold GBs of them).
DOWNLOAD_IGNORE_PATTERNS = [
    "*.h5",
    "*.ot",
    "*.msgpack",
    "*.tflite",
    "onnx/*",
    "openvino/*",
]


@runtime_checkable
class Embedder(Protocol):
    """What the service needs from the loaded model."""

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


@runtime_checkable
class EmbeddingBackend(Protocol):
    model_id: str
    revision: str
    dim: int
    max_batch: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def is_ready(self) -> bool: ...


class SentenceTransformersEmbedding:
    """A loaded, pinned embedding model."""

    def __init__(
        self,
        model_id: str,
        resolved: ResolvedModel,
        embedder: Embedder,
        max_batch: int,
    ) -> None:
        self.model_id = model_id
        self.revision = resolved.revision
        self.weights_sha256 = resolved.weights_sha256
        self.max_batch = max_batch
        self._embedder = embedder
        # One forward pass at a time: the model is not asked to be re-entrant.
        self._lock = threading.Lock()
        self.dim = int(self._run([_PROBE_TEXT]).shape[1])

    def _run(self, texts: Sequence[str]) -> np.ndarray:
        with self._lock:
            return np.asarray(self._embedder.embed(texts), dtype=np.float32)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            vectors = self._run(texts)
        except Exception as exc:
            # The message can echo input; the class name cannot.
            logger.error("embedding failed: %s", type(exc).__name__)
            raise ModelUnavailableError("the embedding model failed") from exc
        if vectors.shape != (len(texts), self.dim) or not np.isfinite(vectors).all():
            logger.error("embedding model returned an unusable batch")
            raise ModelUnavailableError(
                "the embedding model returned an unusable batch"
            )
        return vectors.tolist()

    def is_ready(self) -> bool:
        return True


@dataclass(frozen=True)
class UnavailableEmbedding:
    """Configured and pinned, but the pinned weights are not in the cache."""

    model_id: str
    revision: str
    reason: str
    dim: int = 0
    max_batch: int = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise ModelUnavailableError(self.reason)

    def is_ready(self) -> bool:
        return False


def _load_sentence_transformers(path: Path) -> Embedder:
    try:
        from retrieval.adapters.sentence_transformers import (
            SentenceTransformersAdapter,
        )
    except ImportError as exc:
        raise BackendConfigError(
            "embedding: dependencies missing; install encoder-service with the `embed` "
            "extra (Docker: --build-arg ENCODER_EXTRAS=embed) or unset EMBEDDING_MODEL"
        ) from exc
    return SentenceTransformersAdapter(model_id=str(path), device="cpu")


def build_embedding_backend(
    settings: EmbeddingSettings,
    *,
    cache_dir: Path | None = None,
    load: Callable[[Path], Embedder] | None = None,
) -> EmbeddingBackend | UnavailableEmbedding | None:
    """Build the pinned embedding model; None when EMBEDDING_MODEL is unset."""
    if settings.model is None:
        return None
    if settings.device != "cpu":
        raise BackendConfigError(
            f"ENCODER_DEVICE must be 'cpu' (ADR-0008), got {settings.device!r}"
        )
    revision = settings.revision or ""
    try:
        resolved = resolve_pinned_model(
            settings.model,
            revision=settings.revision,
            expected_sha256=settings.weights_sha256,
            cache_dir=cache_dir,
        )
    except ModelNotCachedError as exc:
        logger.warning("embedding model not cached: /v1/embed answers 503 (%s)", exc)
        return UnavailableEmbedding(
            model_id=settings.model,
            revision=revision,
            reason=(
                f"the embedding model {settings.model} at revision {revision} is "
                "not in this server's cache; run the warmup "
                "(make warmup-retrieval) with network"
            ),
        )
    except PinError as exc:
        raise BackendConfigError(f"embedding: {exc}") from exc

    try:
        embedder = (load or _load_sentence_transformers)(resolved.path)
    except BackendConfigError:
        raise
    except Exception as exc:
        raise BackendConfigError(
            f"embedding: cannot load {settings.model!r}: {type(exc).__name__}"
        ) from exc
    try:
        backend = SentenceTransformersEmbedding(
            settings.model, resolved, embedder, settings.max_batch
        )
    except Exception as exc:
        raise BackendConfigError(
            f"embedding: {settings.model!r} failed its startup probe "
            f"({type(exc).__name__})"
        ) from exc
    logger.info(
        "embedding model %s@%s ready (dim %d)",
        backend.model_id,
        backend.revision,
        backend.dim,
    )
    return backend


def download_pinned(settings: EmbeddingSettings) -> None:
    """Fetch the pinned revision into the hub cache. For the warmup (has network)."""
    if settings.model is None or not settings.revision:
        return
    if Path(settings.model).is_dir():
        return
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise BackendConfigError(
            "warmup: huggingface_hub is missing; install encoder-service with the "
            "`embed` extra"
        ) from exc
    snapshot_download(
        settings.model,
        revision=settings.revision,
        ignore_patterns=DOWNLOAD_IGNORE_PATTERNS,
    )


def readiness(backend: Any) -> dict[str, Any]:
    """The embedding entry of /ready."""
    if backend is None:
        return {"configured": False}
    if backend.is_ready():
        return {
            "configured": True,
            "state": "ready",
            "model_id": backend.model_id,
            "revision": backend.revision,
            "dim": backend.dim,
        }
    return {
        "configured": True,
        "state": "unavailable",
        "model_id": backend.model_id,
        "revision": backend.revision,
        "reason": backend.reason,
    }


# -- The process-wide backend (injected in tests, like the legacy one) --

_active: EmbeddingBackend | UnavailableEmbedding | None = None


def get_embedding() -> EmbeddingBackend | UnavailableEmbedding | None:
    return _active


def set_embedding(backend: EmbeddingBackend | UnavailableEmbedding | None) -> None:
    global _active
    _active = backend
