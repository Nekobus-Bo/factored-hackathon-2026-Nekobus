"""Pins for model weights, checked before a model is loaded (ADR-0012, App. B, J).

A pin is a Hugging Face commit (a full 40-hex revision) and/or the SHA-256 of the
primary weights file. Both are verified against the local Hugging Face cache;
nothing here touches the network. A branch or tag is not a pin: it can move.

The cache layout is the one ``huggingface_hub`` writes::

    <hub cache>/models--<org>--<name>/snapshots/<commit>/<files>
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_HUB_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?$"
)
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
# Tried in order; the first one present is the file the pin refers to.
WEIGHTS_FILES = ("model.safetensors", "pytorch_model.bin")
_CHUNK = 1024 * 1024


class PinError(RuntimeError):
    """A pin is missing, malformed or not satisfied. The message names what to fix."""


class PinMismatchError(PinError):
    """The model on disk is not the one the pin names."""


class ModelNotCachedError(PinMismatchError):
    """The pinned revision is not in the local cache (for example, no network on the
    first run). Distinct so a caller can degrade instead of stopping."""


@dataclass(frozen=True)
class ResolvedModel:
    """A model directory whose pin has been verified."""

    path: Path
    revision: str
    weights_sha256: str


def hub_cache_dir(environ: Mapping[str, str] | None = None) -> Path:
    """The Hugging Face hub cache: HF_HUB_CACHE, else HF_HOME/hub, else the default."""
    env = os.environ if environ is None else environ
    if env.get("HF_HUB_CACHE"):
        return Path(env["HF_HUB_CACHE"])
    if env.get("HF_HOME"):
        return Path(env["HF_HOME"]) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def is_commit(revision: str | None) -> bool:
    return bool(revision) and COMMIT_PATTERN.match(revision or "") is not None


def sha256_hex(value: str | None, what: str) -> str | None:
    """Validate an optional SHA-256 given as configuration."""
    if value is None or not value.strip():
        return None
    cleaned = value.strip().lower()
    if not _SHA256_PATTERN.match(cleaned):
        raise PinError(f"{what} must be 64 hexadecimal characters")
    return cleaned


def cached_snapshot(model: str, revision: str, cache_dir: Path | None = None) -> Path:
    """The cached snapshot of a hub model at exactly ``revision``."""
    if not _HUB_ID_PATTERN.match(model):
        raise PinError(
            f"{model!r} is not a Hugging Face model id or an existing directory"
        )
    if not is_commit(revision):
        raise PinError(
            f"revision {revision!r} for {model!r} must be a full 40-hex commit "
            "(a branch or tag is not a pin)"
        )
    repo = (cache_dir or hub_cache_dir()) / f"models--{model.replace('/', '--')}"
    snapshot = repo / "snapshots" / revision
    if not snapshot.is_dir():
        raise ModelNotCachedError(
            f"{model!r} at revision {revision} is not in the local cache "
            f"({repo}); download it with the warmup command"
        )
    return snapshot


def weights_file(directory: Path) -> Path:
    """The primary weights file of a model directory."""
    for name in WEIGHTS_FILES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    raise PinMismatchError(
        f"no weights file ({' or '.join(WEIGHTS_FILES)}) in {directory}"
    )


def weights_sha256(directory: Path) -> str:
    """SHA-256 of the primary weights file, streamed."""
    digest = hashlib.sha256()
    with weights_file(directory).open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_pinned_model(
    model: str,
    *,
    revision: str | None,
    expected_sha256: str | None,
    cache_dir: Path | None = None,
) -> ResolvedModel:
    """Find ``model`` on disk and verify its pin; raise a ``PinError`` otherwise.

    * A hub id needs a 40-hex ``revision`` and must be cached at exactly that commit.
      ``expected_sha256`` is optional and, when given, is verified.
    * An existing directory has no commit, so it needs ``expected_sha256`` and a
      ``revision`` label (a name for humans, not verified).
    """
    directory = Path(model)
    if directory.is_dir():
        if expected_sha256 is None:
            raise PinError(
                f"{model!r} is a local directory: set the weights SHA-256 pin "
                "(EMBEDDING_WEIGHTS_SHA256), a directory has no commit to pin"
            )
        if not revision or not _LABEL_PATTERN.match(revision):
            raise PinError(
                f"{model!r} is a local directory: set a revision label "
                "(letters, digits, '.', '_', ':', '-'; at most 64 characters)"
            )
        actual = weights_sha256(directory)
        _check_hash(model, actual, expected_sha256)
        return ResolvedModel(path=directory, revision=revision, weights_sha256=actual)

    if not revision:
        raise PinError(f"{model!r} needs a pinned revision (a full 40-hex commit)")
    snapshot = cached_snapshot(model, revision, cache_dir)
    actual = weights_sha256(snapshot)
    if expected_sha256 is not None:
        _check_hash(model, actual, expected_sha256)
    return ResolvedModel(path=snapshot, revision=revision, weights_sha256=actual)


def _check_hash(model: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise PinMismatchError(
            f"{model!r}: weights SHA-256 is {actual[:12]}..., "
            f"the pin says {expected[:12]}...; these are not the pinned weights"
        )
