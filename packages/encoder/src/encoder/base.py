from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from encoder.models import DecisionExample, DecisionPrediction

# distribution: `predict` fills `probabilities` for every label of the backend's
# label space, summing to 1 (+/- 1e-3). Calibrators and group views need it.
# top1_only: only the top label and its confidence mean anything (GLiNER today);
# the rest of `probabilities` is filler. Such a backend supports a plain threshold.
ProbabilityKind = Literal["distribution", "top1_only"]


class DecisionAdapter(ABC):
    """Abstract adapter interface for decision (intent + slots) models.

    A subclass declares ``kind`` (its key in ``encoder.registry``) and
    ``probability_kind``. The conformance test
    (``packages/encoder/tests/test_adapter_conformance.py``) is the checklist for a
    new adapter (ADR-0012, Appendix C).
    """

    name: str
    kind: ClassVar[str]
    probability_kind: ClassVar[ProbabilityKind]

    @abstractmethod
    def fit(
        self,
        train_examples: Sequence[DecisionExample],
        val_examples: Sequence[DecisionExample] | None = None,
        epochs: int = 3,
        batch_size: int = 8,
        learning_rate: float = 5e-5,
    ) -> None:
        """Fit or fine-tune adapter on training split."""

    @abstractmethod
    def predict(
        self,
        texts: Sequence[str],
        candidate_intents: Sequence[str] | None = None,
        candidate_slots: Sequence[str] | None = None,
    ) -> list[DecisionPrediction]:
        """Generate predictions for a sequence of texts."""

    @abstractmethod
    def save(self, path: str | Path) -> None:
        """Persist adapter weights to path."""

    @abstractmethod
    def load(self, path: str | Path) -> None:
        """Load adapter weights from path."""
