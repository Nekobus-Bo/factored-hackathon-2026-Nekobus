"""Manifest of a trained model directory: what the weights are and where they came from.

A fine-tuned model (``hf_seqcls``) is a directory, not a hub commit, so its pin is
the SHA-256 of the primary weights file plus a revision label (``encoder.pinning``).
The manifest closes the rest of the gap (ADR-0014, Appendix A):

* every file in the directory is listed with its SHA-256, and nothing else may be
  there (a tokenizer or config swapped next to pinned weights is caught);
* only safetensors weights are allowed, never a pickle;
* the revision label is ``<name>:<12 hex of the manifest's SHA-256>``, so the
  artifact's ``revision`` pins the whole directory, not only the weights file;
* it records the base model commit, the label order, the data hashes and the
  hyper-parameters, so a retrain can be compared with the one it replaces.

This module does not import PyTorch: the service, the harness and CI verify a
directory without loading the model.

    python -m encoder.weights verify packages/encoder/weights/distilbert-intent-pooled
    python -m encoder.weights show packages/encoder/weights/distilbert-intent-pooled
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from encoder.pinning import PinMismatchError, weights_sha256

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1
# The files a saved sequence classifier may hold. Anything else in the directory
# (a pickle, a stray checkpoint, an OS file) fails verification.
ALLOWED_FILES = frozenset(
    {
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "vocab.txt",
    }
)
REQUIRED_FILES = frozenset(
    {"config.json", "model.safetensors", "tokenizer_config.json"}
)
_CHUNK = 1024 * 1024


class ManifestError(PinMismatchError):
    """The directory is not the one its manifest describes, or has no valid manifest."""


class DataFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    split: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: int = Field(ge=0)


class WeightsManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = MANIFEST_SCHEMA_VERSION
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,47}$")
    kind: str = Field(min_length=1)
    base_model: str = Field(min_length=1)
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    labels: list[str] = Field(min_length=2)
    max_length: int = Field(ge=8, le=4096, description="Tokens when scoring")
    train_max_length: int = Field(ge=8, le=4096, description="Tokens when training")
    hyperparameters: dict[str, Any]
    data: list[DataFile]
    environment: dict[str, str]
    metrics: dict[str, dict[str, float]] = Field(default_factory=dict)
    files: dict[str, str] = Field(description="File name -> SHA-256")

    def sha256(self) -> str:
        """SHA-256 of the canonical JSON of this manifest."""
        return manifest_sha256(self)

    def revision_label(self) -> str:
        """The artifact's ``revision`` for this directory: ``<name>:<12 hex>``."""
        return f"{self.name}:{self.sha256()[:12]}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_sha256(manifest: WeightsManifest) -> str:
    canonical = json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hash_files(directory: Path) -> dict[str, str]:
    """SHA-256 of every file in ``directory`` except the manifest, checked against the
    allowlist. Raises ``ManifestError`` on a subdirectory or a file not allowed."""
    hashes: dict[str, str] = {}
    for entry in sorted(directory.iterdir()):
        if entry.name == MANIFEST_NAME:
            continue
        if not entry.is_file():
            raise ManifestError(f"{directory}: unexpected entry {entry.name!r}")
        if entry.name not in ALLOWED_FILES:
            raise ManifestError(
                f"{directory}: file {entry.name!r} is not allowed next to the weights "
                f"(allowed: {', '.join(sorted(ALLOWED_FILES))})"
            )
        hashes[entry.name] = file_sha256(entry)
    missing = REQUIRED_FILES - set(hashes)
    if missing:
        raise ManifestError(f"{directory}: missing {', '.join(sorted(missing))}")
    return hashes


def write_manifest(directory: Path, **fields: Any) -> WeightsManifest:
    """Hash the directory, validate the fields and write ``manifest.json``."""
    manifest = WeightsManifest(files=hash_files(directory), **fields)
    (directory / MANIFEST_NAME).write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_manifest(directory: Path) -> WeightsManifest:
    path = directory / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(f"{directory}: no {MANIFEST_NAME}; not a trained model dir")
    try:
        return WeightsManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ManifestError(
            f"{path}: invalid manifest: {exc.error_count()} error(s)"
        ) from exc


def verify_manifest(directory: Path) -> WeightsManifest:
    """The manifest, after checking that the directory holds exactly the files it
    lists, with the same hashes. Raises ``ManifestError`` otherwise."""
    manifest = load_manifest(directory)
    actual = hash_files(directory)
    if set(actual) != set(manifest.files):
        extra = sorted(set(actual) - set(manifest.files))
        gone = sorted(set(manifest.files) - set(actual))
        raise ManifestError(
            f"{directory}: files differ from the manifest "
            f"(extra {extra}, missing {gone})"
        )
    changed = sorted(
        name for name, sha in actual.items() if manifest.files[name] != sha
    )
    if changed:
        raise ManifestError(
            f"{directory}: {', '.join(changed)} changed since the manifest was written"
        )
    if manifest.files["model.safetensors"] != weights_sha256(directory):
        raise ManifestError(
            f"{directory}: the primary weights file is not model.safetensors"
        )
    return manifest


def pins(directory: Path) -> dict[str, str]:
    """The values an artifact backend pins for ``directory`` (after verification)."""
    manifest = verify_manifest(directory)
    return {
        "revision": manifest.revision_label(),
        "weights_sha256": manifest.files["model.safetensors"],
        "manifest_sha256": manifest.sha256(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m encoder.weights")
    parser.add_argument("command", choices=("verify", "show"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = verify_manifest(args.directory)
    except ManifestError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.command == "verify":
        weights = manifest.files["model.safetensors"]
        print(f"OK {manifest.revision_label()} weights_sha256={weights}")
    else:
        print(
            json.dumps(
                {
                    **pins(args.directory),
                    "labels": manifest.labels,
                    "max_length": manifest.max_length,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
