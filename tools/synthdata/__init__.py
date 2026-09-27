"""Synthetic dataset generator for intent and slot models."""

import sys
from pathlib import Path

# Ensure repository root is on sys.path when tools package is loaded
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def __getattr__(name: str):
    if name in ("generate_datasets", "generate_split"):
        from tools.synthdata.generate import generate_datasets, generate_split

        return {
            "generate_datasets": generate_datasets,
            "generate_split": generate_split,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["generate_datasets", "generate_split"]
