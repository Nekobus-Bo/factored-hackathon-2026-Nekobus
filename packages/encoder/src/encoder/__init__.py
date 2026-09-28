from typing import TYPE_CHECKING

from encoder.adapters import TFIDFLRAdapter
from encoder.base import DecisionAdapter
from encoder.models import DecisionExample, DecisionPrediction, Slot

if TYPE_CHECKING:
    from encoder.adapters.gliner import GLiNERAdapter


def __getattr__(name: str) -> object:
    # Lazy: GLiNERAdapter imports torch, which only the `gliner` extra installs.
    if name == "GLiNERAdapter":
        from encoder.adapters.gliner import GLiNERAdapter

        return GLiNERAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DecisionAdapter",
    "DecisionExample",
    "DecisionPrediction",
    "Slot",
    "TFIDFLRAdapter",
    "GLiNERAdapter",
]
