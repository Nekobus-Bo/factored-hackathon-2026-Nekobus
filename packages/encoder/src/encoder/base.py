from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from encoder.models import DecisionExample, DecisionPrediction


class DecisionAdapter(ABC):
    """Abstract adapter interface for decision (intent + slots) models."""

    name: str

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
