"""Configuration management for encoder service."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from contracts.encoder import EMBED_MAX_BATCH
from encoder.decision_points import DEFAULT_ARTIFACT_PATH, parse_tau_raise
from encoder.pinning import PinError, sha256_hex

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


DEFAULT_DECISION_WORKERS = 4
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class DecisionPointSettings:
    """Decision-point configuration, read from the environment (ADR-0012, Appendix B).

    Only paths and switches live here. Every tau, label map and calibrator lives in
    the calibration artifact.
    """

    file: Path
    # True when DECISION_POINTS_FILE was set: a missing file is then reported.
    file_explicit: bool
    allow_stale: bool
    tau_raise: Mapping[tuple[str, str], float]
    max_workers: int
    app_env: str


def _flag(environ: Mapping[str, str], name: str) -> bool:
    raw = environ.get(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ValueError(f"{name} must be true or false, got {raw!r}")


def get_decision_point_settings(
    environ: Mapping[str, str] | None = None,
) -> DecisionPointSettings:
    """Read DECISION_POINTS_* (see .env.example). Invalid values fail loudly."""
    env = os.environ if environ is None else environ
    app_env = env.get("APP_ENV", "").strip().lower()
    allow_stale = _flag(env, "DECISION_POINTS_ALLOW_STALE")
    if allow_stale and app_env == "production":
        raise ValueError(
            "DECISION_POINTS_ALLOW_STALE is refused when APP_ENV=production: a model "
            "that does not match its pin must stop the service, not serve"
        )
    raw_workers = env.get("DECISION_POINTS_MAX_WORKERS", "").strip()
    try:
        workers = int(raw_workers) if raw_workers else DEFAULT_DECISION_WORKERS
    except ValueError as err:
        raise ValueError(
            f"DECISION_POINTS_MAX_WORKERS must be an integer, got {raw_workers!r}"
        ) from err
    if workers < 1:
        raise ValueError("DECISION_POINTS_MAX_WORKERS must be at least 1")
    explicit = env.get("DECISION_POINTS_FILE", "").strip()
    return DecisionPointSettings(
        file=Path(explicit or DEFAULT_ARTIFACT_PATH),
        file_explicit=bool(explicit),
        allow_stale=allow_stale,
        tau_raise=parse_tau_raise(env.get("DECISION_POINTS_TAU_RAISE")),
        max_workers=workers,
        app_env=app_env,
    )


DEFAULT_EMBEDDING_MAX_BATCH = 64
# Precision the embedding weights load in (EMBEDDING_DTYPE). float32 by default: a
# model that ships bf16 weights would otherwise run in bf16, slow on CPUs without it.
EMBEDDING_DTYPES = ("float32", "bfloat16")
DEFAULT_EMBEDDING_DTYPE = "float32"


@dataclass(frozen=True)
class EmbeddingSettings:
    """The embedding model served by POST /v1/embed (ADR-0012, Appendix J).

    Pinned like a decision backend: a hub model needs a full 40-hex commit, a local
    directory needs its weights SHA-256. Unset ``model`` disables /v1/embed.
    """

    model: str | None
    revision: str | None
    weights_sha256: str | None
    max_batch: int
    device: str
    dtype: str = DEFAULT_EMBEDDING_DTYPE


def get_embedding_settings(
    environ: Mapping[str, str] | None = None,
) -> EmbeddingSettings:
    """Read EMBEDDING_* (see .env.example). Invalid values fail loudly."""
    env = os.environ if environ is None else environ
    raw_batch = env.get("EMBEDDING_MAX_BATCH", "").strip()
    try:
        max_batch = int(raw_batch) if raw_batch else DEFAULT_EMBEDDING_MAX_BATCH
    except ValueError as err:
        raise ValueError(
            f"EMBEDDING_MAX_BATCH must be an integer, got {raw_batch!r}"
        ) from err
    if not 1 <= max_batch <= EMBED_MAX_BATCH:
        raise ValueError(
            f"EMBEDDING_MAX_BATCH must be between 1 and {EMBED_MAX_BATCH} "
            "(the contract ceiling)"
        )
    raw_dtype = env.get("EMBEDDING_DTYPE", "").strip().lower()
    dtype = raw_dtype or DEFAULT_EMBEDDING_DTYPE
    if dtype not in EMBEDDING_DTYPES:
        allowed = ", ".join(EMBEDDING_DTYPES)
        raise ValueError(f"EMBEDDING_DTYPE must be one of {allowed}, got {dtype!r}")
    try:
        weights = sha256_hex(
            env.get("EMBEDDING_WEIGHTS_SHA256"), "EMBEDDING_WEIGHTS_SHA256"
        )
    except PinError as err:
        raise ValueError(str(err)) from err
    return EmbeddingSettings(
        model=env.get("EMBEDDING_MODEL", "").strip() or None,
        revision=env.get("EMBEDDING_REVISION", "").strip() or None,
        weights_sha256=weights,
        max_batch=max_batch,
        device=env.get("ENCODER_DEVICE", "cpu").strip() or "cpu",
        dtype=dtype,
    )
