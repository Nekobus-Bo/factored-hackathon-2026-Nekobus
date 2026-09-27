"""Pluggable inference backend interface for the encoder service."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class ModelUnavailableError(Exception):
    """Raised when no model backend is configured or model is unavailable."""

    pass


@dataclass(frozen=True)
class RawSlot:
    """Raw slot extracted by an inference backend."""

    type: str
    value: str
    start: int
    end: int
    normalized: str | None = None


@dataclass(frozen=True)
class RawPiiSpan:
    """Raw PII span detected by an inference backend."""

    type: str
    start: int
    end: int


@dataclass(frozen=True)
class RawAnalysisResult:
    """Raw result emitted by an inference backend."""

    intent: str | None
    confidence: float
    slots: list[RawSlot] = field(default_factory=list)
    pii_spans: list[RawPiiSpan] = field(default_factory=list)
    model_id: str = "unavailable"


@runtime_checkable
class EncoderBackend(Protocol):
    """Protocol for pluggable encoder inference backends."""

    model_id: str

    def analyze(self, text: str, lang: str | None = None) -> RawAnalysisResult:
        """Run intent and slot inference on input text."""
        ...

    def is_ready(self) -> bool:
        """Check if backend is ready to serve requests."""
        ...


class UnavailableBackend:
    """Default backend when no model is configured.

    Fails loud with 503 rather than producing fake output.
    """

    model_id: str = "unavailable"

    def analyze(self, text: str, lang: str | None = None) -> RawAnalysisResult:
        raise ModelUnavailableError(
            "Encoder model is not configured or unavailable. "
            "Set ENCODER_MODEL or configure an inference backend."
        )

    def is_ready(self) -> bool:
        return False


# Global backend registry
_active_backend: EncoderBackend | None = None


def get_backend() -> EncoderBackend:
    """Retrieve the currently configured inference backend."""
    global _active_backend
    if _active_backend is not None:
        return _active_backend

    return UnavailableBackend()


def set_backend(backend: EncoderBackend | None) -> None:
    """Override or reset the active backend (e.g. injected in tests)."""
    global _active_backend
    _active_backend = backend
