"""Fake encoder backend for test fixtures."""

from encoder_service.backend import (
    ModelUnavailableError,
    RawAnalysisResult,
    RawPiiSpan,
    RawSlot,
)


class FakeEncoderBackend:
    """Configurable fake backend for testing."""

    def __init__(
        self,
        intent: str | None = "request_card_block",
        confidence: float = 0.95,
        slots: list[RawSlot] | None = None,
        pii_spans: list[RawPiiSpan] | None = None,
        model_id: str = "fake-encoder-v1",
        ready: bool = True,
    ) -> None:
        self.intent = intent
        self.confidence = confidence
        self.slots = list(slots) if slots is not None else []
        self.pii_spans = list(pii_spans) if pii_spans is not None else []
        self.model_id = model_id
        self._ready = ready

    def analyze(self, text: str, lang: str | None = None) -> RawAnalysisResult:
        if not self._ready:
            raise ModelUnavailableError("Fake backend marked unready")
        return RawAnalysisResult(
            intent=self.intent,
            confidence=self.confidence,
            slots=self.slots,
            pii_spans=self.pii_spans,
            model_id=self.model_id,
        )

    def is_ready(self) -> bool:
        return self._ready
