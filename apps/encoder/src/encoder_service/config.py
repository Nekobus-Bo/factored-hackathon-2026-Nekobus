"""Configuration management for encoder service."""

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TRAIN_DATA = "data/eval/synthetic/decision.train.jsonl"
# gliner2.5-multi peaks at ~3.5 GB RSS on CPU (make encoder-bench).
DEFAULT_GLINER_MIN_MEMORY_MB = 4096


@dataclass(frozen=True)
class BackendSettings:
    """Inference backend selection, read from the environment."""

    backend: str | None
    model: str | None
    device: str
    train_data: Path
    gliner_min_memory_mb: int = DEFAULT_GLINER_MIN_MEMORY_MB


def get_backend_settings() -> BackendSettings:
    """Read the ENCODER_* backend variables (see .env.example)."""
    raw_floor = os.getenv("ENCODER_GLINER_MIN_MEMORY_MB", "").strip()
    try:
        floor = int(raw_floor) if raw_floor else DEFAULT_GLINER_MIN_MEMORY_MB
    except ValueError as err:
        raise ValueError(
            f"ENCODER_GLINER_MIN_MEMORY_MB must be an integer, got {raw_floor!r}"
        ) from err
    return BackendSettings(
        backend=os.getenv("ENCODER_BACKEND", "").strip() or None,
        model=os.getenv("ENCODER_MODEL", "").strip() or None,
        device=os.getenv("ENCODER_DEVICE", "cpu").strip() or "cpu",
        train_data=Path(
            os.getenv("ENCODER_TRAIN_DATA", "").strip() or DEFAULT_TRAIN_DATA
        ),
        gliner_min_memory_mb=floor,
    )


def get_abstention_threshold() -> float | None:
    """Retrieve the abstention threshold (tau) from the environment.

    Returns:
        float | None: The calibrated threshold if set, or None if uncalibrated.

    Raises:
        ValueError: If ABSTENTION_THRESHOLD is present but not a valid float in [0, 1].
    """
    raw_val = os.getenv("ABSTENTION_THRESHOLD")
    if raw_val is None or not raw_val.strip():
        return None

    cleaned = raw_val.strip()
    try:
        tau = float(cleaned)
    except ValueError as err:
        raise ValueError(
            f"ABSTENTION_THRESHOLD must be a valid float in [0.0, 1.0], got '{raw_val}'"
        ) from err

    if not (0.0 <= tau <= 1.0):
        raise ValueError(f"ABSTENTION_THRESHOLD must be between 0.0 and 1.0, got {tau}")

    return tau
