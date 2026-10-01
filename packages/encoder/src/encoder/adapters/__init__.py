from typing import TYPE_CHECKING

from encoder.adapters.tfidf_lr import TFIDFLRAdapter

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


__all__ = ["TFIDFLRAdapter", "GLiNERAdapter", "HFSequenceClassifierAdapter"]
