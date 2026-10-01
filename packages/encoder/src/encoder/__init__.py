from typing import TYPE_CHECKING

from encoder.adapters import TFIDFLRAdapter
from encoder.base import DecisionAdapter
from encoder.models import DecisionExample, DecisionPrediction, Slot

if TYPE_CHECKING:
    from encoder.adapters.gliner import GLiNERAdapter
    from encoder.adapters.hf_seqcls import HFSequenceClassifierAdapter


def __getattr__(name: str) -> object:
    # Lazy: these import torch, which only the `gliner` and `hf` extras install.
    if name == "GLiNERAdapter":
        from encoder.adapters.gliner import GLiNERAdapter

        return GLiNERAdapter
    if name == "HFSequenceClassifierAdapter":
        from encoder.adapters.hf_seqcls import HFSequenceClassifierAdapter

        return HFSequenceClassifierAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DecisionAdapter",
    "DecisionExample",
    "DecisionPrediction",
    "Slot",
    "TFIDFLRAdapter",
    "GLiNERAdapter",
    "HFSequenceClassifierAdapter",
]
