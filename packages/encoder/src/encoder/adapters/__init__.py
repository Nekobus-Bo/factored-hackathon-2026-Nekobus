from typing import TYPE_CHECKING

from encoder.adapters.tfidf_lr import TFIDFLRAdapter

if TYPE_CHECKING:
    from encoder.adapters.gliner import GLiNERAdapter


def __getattr__(name: str) -> object:
    # Lazy: GLiNERAdapter imports torch, which only the `gliner` extra installs.
    if name == "GLiNERAdapter":
        from encoder.adapters.gliner import GLiNERAdapter

        return GLiNERAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["TFIDFLRAdapter", "GLiNERAdapter"]
