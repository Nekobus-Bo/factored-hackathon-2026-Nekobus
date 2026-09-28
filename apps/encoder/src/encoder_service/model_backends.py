"""Real inference backends wrapping packages/encoder adapters.

Selected by ENCODER_BACKEND (see config.get_backend_settings):
- ``tfidf_lr``: TF-IDF + logistic regression trained in memory at startup on the
  versioned synthetic train split, plus regex slots. No artifact: the model is a
  pure function of the train file, and model_id carries that file's SHA-256.
- ``gliner``: a GLiNER2 model (ENCODER_MODEL, a hub id or a local directory)
  for intents, slots and PII spans. Weights live in the Hugging Face cache
  (HF_HOME), never in git; ``make warmup`` fills that cache.
Inference is CPU only (ADR-0008). tau is not decided here: abstention stays in
main.analyze, driven by ABSTENTION_THRESHOLD.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from contracts.labels import Intent, PiiType, SlotType
from encoder.adapters import TFIDFLRAdapter
from encoder.models import DecisionExample, Slot
from encoder.regex_slots import extract_regex_slots

from encoder_service.backend import (
    EncoderBackend,
    RawAnalysisResult,
    RawPiiSpan,
    RawSlot,
)
from encoder_service.config import BackendSettings

if TYPE_CHECKING:
    from encoder.base import DecisionAdapter

logger = logging.getLogger(__name__)

# Slots that carry PII (schema.yaml `pii: true`) and their masking category.
SLOT_PII_TYPES: dict[SlotType, PiiType] = {
    SlotType.DOCUMENT_NUMBER: PiiType.DOC,
    SlotType.FULL_NAME: PiiType.NAME,
    SlotType.BIRTH_DATE: PiiType.DATE,
    SlotType.EMAIL: PiiType.EMAIL,
    SlotType.PHONE: PiiType.PHONE,
    SlotType.CARD_NUMBER: PiiType.CARD,
    SlotType.OTP_CODE: PiiType.OTP,
}


# cgroup v2 memory limit of this container.
CGROUP_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")


class BackendConfigError(RuntimeError):
    """The configured backend cannot be built; the service must not start."""


def _raw_slots(slots: list[Slot]) -> list[RawSlot]:
    return [
        RawSlot(type=s.type, value=s.value, start=s.start, end=s.end) for s in slots
    ]


def pii_spans_from_slots(slots: list[Slot]) -> list[RawPiiSpan]:
    """PII spans for the slots whose type carries PII (SLOT_PII_TYPES)."""
    spans = []
    for slot in slots:
        # Unknown slot types pass through here and are rejected in main.analyze.
        pii_type = SLOT_PII_TYPES.get(slot.type)
        if pii_type is not None:
            spans.append(
                RawPiiSpan(type=pii_type.value, start=slot.start, end=slot.end)
            )
    return spans


def check_memory_floor(min_mb: int, memory_max: Path) -> None:
    """Refuse to start when the cgroup memory limit is below min_mb.

    An unreadable file or "max" (no limit) cannot be checked: start and warn.
    """
    try:
        raw = memory_max.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning(
            "gliner: cannot read %s (%s); memory floor unchecked", memory_max, exc
        )
        return
    if raw == "max":
        logger.warning("gliner: no cgroup memory limit; memory floor unchecked")
        return
    try:
        limit_mb = int(raw) // (1024 * 1024)
    except ValueError:
        logger.warning(
            "gliner: unexpected %s content %r; memory floor unchecked", memory_max, raw
        )
        return
    if limit_mb < min_mb:
        raise BackendConfigError(
            f"gliner: container memory limit is {limit_mb} MiB, below the "
            f"{min_mb} MiB floor (ENCODER_GLINER_MIN_MEMORY_MB); raise "
            "ENCODER_MEMORY_LIMIT or use ENCODER_BACKEND=tfidf_lr"
        )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TfidfLrBackend:
    """Lexical baseline: intents from TF-IDF + LR, slots and PII spans from regex."""

    def __init__(self, train_path: Path) -> None:
        if not train_path.is_file():
            raise BackendConfigError(
                f"tfidf_lr: train data not found at {train_path} "
                "(set ENCODER_TRAIN_DATA)"
            )
        lines = train_path.read_text(encoding="utf-8").splitlines()
        examples = [DecisionExample(**json.loads(line)) for line in lines if line]
        train = [e for e in examples if e.split == "train"]
        if not train:
            raise BackendConfigError(f"tfidf_lr: no split=train rows in {train_path}")
        labels = {e.intent for e in train}
        unknown = labels - {i.value for i in Intent}
        if unknown:
            raise BackendConfigError(
                f"tfidf_lr: train data has intents outside contracts: {sorted(unknown)}"
            )

        self._adapter = TFIDFLRAdapter(name="tfidf_lr")
        self._adapter.fit(train)
        self.model_id = f"tfidf_lr@train-sha256:{file_sha256(train_path)[:12]}"
        logger.info("tfidf_lr trained on %d rows (%s)", len(train), self.model_id)

    def analyze(self, text: str, lang: str | None = None) -> RawAnalysisResult:
        pred = self._adapter.predict([text])[0]
        slots = extract_regex_slots(text)
        return RawAnalysisResult(
            intent=pred.intent,
            confidence=pred.confidence,
            slots=_raw_slots(slots),
            pii_spans=pii_spans_from_slots(slots),
            model_id=self.model_id,
        )

    def is_ready(self) -> bool:
        return True


def _load_gliner(model: str) -> DecisionAdapter:
    try:
        from encoder.adapters import GLiNERAdapter
    except ImportError as exc:
        raise BackendConfigError(
            "gliner: dependencies missing; install encoder-service with the "
            "`gliner` extra (Docker: --build-arg ENCODER_EXTRAS=gliner)"
        ) from exc
    return GLiNERAdapter(model_id=model, device="cpu")


class GlinerBackend:
    """GLiNER2 zero-shot backend: intents, slots, and PII spans from PII slots."""

    def __init__(
        self,
        model: str,
        load_adapter: Callable[[str], DecisionAdapter] = _load_gliner,
    ) -> None:
        try:
            self._adapter = load_adapter(model)
        except BackendConfigError:
            raise
        except Exception as exc:
            raise BackendConfigError(
                f"gliner: cannot load model {model!r}: {exc}"
            ) from exc
        self._intents = [i.value for i in Intent]
        self._slots = [s.value for s in SlotType]
        self.model_id = f"gliner:{model}"

    def analyze(self, text: str, lang: str | None = None) -> RawAnalysisResult:
        pred = self._adapter.predict([text], self._intents, self._slots)[0]
        return RawAnalysisResult(
            intent=pred.intent,
            confidence=pred.confidence,
            slots=_raw_slots(pred.slots),
            pii_spans=pii_spans_from_slots(pred.slots),
            model_id=self.model_id,
        )

    def is_ready(self) -> bool:
        return True


def build_backend(settings: BackendSettings) -> EncoderBackend | None:
    """Build the configured backend; None keeps the service unavailable (503)."""
    if settings.backend is None:
        return None
    if settings.device != "cpu":
        raise BackendConfigError(
            f"ENCODER_DEVICE must be 'cpu' (ADR-0008), got {settings.device!r}"
        )
    if settings.backend == "tfidf_lr":
        return TfidfLrBackend(settings.train_data)
    if settings.backend == "gliner":
        if not settings.model:
            raise BackendConfigError(
                "gliner: set ENCODER_MODEL to a hub id or local dir"
            )
        check_memory_floor(settings.gliner_min_memory_mb, CGROUP_MEMORY_MAX)
        return GlinerBackend(settings.model)
    raise BackendConfigError(
        f"unknown ENCODER_BACKEND {settings.backend!r}; expected tfidf_lr or gliner"
    )
