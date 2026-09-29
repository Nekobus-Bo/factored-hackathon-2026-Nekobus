"""Stub of the ``llm_sidecar`` backend (ADR-0012, Appendix C.3).

A ~4B quantized LLM behind an out-of-process llama.cpp server is a candidate
backend for decision points where cheaper rungs fall short. The container, the
prompt and the calibration are the calibration owner's and come after the
freeze. Until then the kind is registered so an artifact that names it fails
loudly, with this message, instead of falling through to something else
(AGENTS.md, rule 7).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from encoder.base import DecisionAdapter
from encoder.models import DecisionExample, DecisionPrediction

PENDING = "pending: llm_sidecar is not implemented (ADR-0012)"


class LLMSidecarAdapter(DecisionAdapter):
    """Not implemented: constructing it raises ``NotImplementedError(PENDING)``."""

    kind = "llm_sidecar"
    # Confidences would be label log-probabilities softmaxed over the label set.
    probability_kind = "distribution"

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(PENDING)

    def fit(
        self,
        train_examples: Sequence[DecisionExample],
        val_examples: Sequence[DecisionExample] | None = None,
        epochs: int = 3,
        batch_size: int = 8,
        learning_rate: float = 5e-5,
    ) -> NoReturn:
        raise NotImplementedError(PENDING)

    def predict(
        self,
        texts: Sequence[str],
        candidate_intents: Sequence[str] | None = None,
        candidate_slots: Sequence[str] | None = None,
    ) -> list[DecisionPrediction]:
        raise NotImplementedError(PENDING)

    def save(self, path: str | Path) -> NoReturn:
        raise NotImplementedError(PENDING)

    def load(self, path: str | Path) -> NoReturn:
        raise NotImplementedError(PENDING)
