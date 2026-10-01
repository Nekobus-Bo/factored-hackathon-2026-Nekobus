"""Pins: a hub commit and a weights hash, verified against the local cache."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from encoder.pinning import (
    ModelNotCachedError,
    PinError,
    PinMismatchError,
    cached_snapshot,
    hub_cache_dir,
    resolve_pinned_model,
    sha256_hex,
    weights_sha256,
)

COMMIT = "86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d"
OTHER_COMMIT = "0" * 40
WEIGHTS = b"pretend safetensors payload"
WEIGHTS_HASH = hashlib.sha256(WEIGHTS).hexdigest()


def make_cache(root: Path, model: str = "org/model", revision: str = COMMIT) -> Path:
    snapshot = root / f"models--{model.replace('/', '--')}" / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(WEIGHTS)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    return snapshot


def test_hub_cache_dir_follows_the_hf_variables(tmp_path: Path) -> None:
    assert hub_cache_dir({"HF_HUB_CACHE": "/a", "HF_HOME": "/b"}) == Path("/a")
    assert hub_cache_dir({"HF_HOME": "/b"}) == Path("/b/hub")
    assert hub_cache_dir({}) == Path.home() / ".cache" / "huggingface" / "hub"


def test_a_cached_commit_resolves_and_reports_its_weights_hash(tmp_path: Path) -> None:
    snapshot = make_cache(tmp_path)
    resolved = resolve_pinned_model(
        "org/model", revision=COMMIT, expected_sha256=None, cache_dir=tmp_path
    )
    assert resolved.path == snapshot
    assert resolved.revision == COMMIT
    assert resolved.weights_sha256 == WEIGHTS_HASH


def test_the_hash_pin_is_verified_when_given(tmp_path: Path) -> None:
    make_cache(tmp_path)
    resolve_pinned_model(
        "org/model", revision=COMMIT, expected_sha256=WEIGHTS_HASH, cache_dir=tmp_path
    )
    with pytest.raises(PinMismatchError, match="not the pinned weights"):
        resolve_pinned_model(
            "org/model", revision=COMMIT, expected_sha256="1" * 64, cache_dir=tmp_path
        )


def test_a_revision_that_is_not_cached_is_named_and_distinct(tmp_path: Path) -> None:
    make_cache(tmp_path)
    with pytest.raises(ModelNotCachedError, match="is not in the local cache"):
        cached_snapshot("org/model", OTHER_COMMIT, tmp_path)
    # ModelNotCachedError is a PinMismatchError, so a strict caller catches both.
    assert issubclass(ModelNotCachedError, PinMismatchError)


@pytest.mark.parametrize("revision", ["main", "v1.0", COMMIT[:12], COMMIT.upper(), ""])
def test_a_branch_tag_or_short_sha_is_not_a_pin(tmp_path: Path, revision: str) -> None:
    make_cache(tmp_path)
    with pytest.raises(PinError):
        resolve_pinned_model(
            "org/model", revision=revision, expected_sha256=None, cache_dir=tmp_path
        )


def test_a_hub_model_without_a_revision_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PinError, match="needs a pinned revision"):
        resolve_pinned_model(
            "org/model", revision=None, expected_sha256=None, cache_dir=tmp_path
        )


@pytest.mark.parametrize("model", ["../etc", "a/b/c", "org/mod el", "/abs/path", ""])
def test_a_malformed_model_id_is_refused(tmp_path: Path, model: str) -> None:
    with pytest.raises(PinError):
        cached_snapshot(model, COMMIT, tmp_path)


def test_a_snapshot_without_weights_cannot_be_hashed(tmp_path: Path) -> None:
    snapshot = make_cache(tmp_path)
    (snapshot / "model.safetensors").unlink()
    with pytest.raises(PinMismatchError, match="no weights file"):
        weights_sha256(snapshot)


def test_pytorch_bin_is_the_fallback_weights_file(tmp_path: Path) -> None:
    snapshot = make_cache(tmp_path)
    (snapshot / "model.safetensors").unlink()
    (snapshot / "pytorch_model.bin").write_bytes(b"bin")
    assert weights_sha256(snapshot) == hashlib.sha256(b"bin").hexdigest()


def test_a_local_directory_needs_a_hash_and_a_label(tmp_path: Path) -> None:
    model = tmp_path / "fine-tuned"
    model.mkdir()
    (model / "model.safetensors").write_bytes(WEIGHTS)
    with pytest.raises(PinError, match="set the weights SHA-256 pin"):
        resolve_pinned_model(
            str(model), revision="ft-1", expected_sha256=None, cache_dir=tmp_path
        )
    with pytest.raises(PinError, match="revision label"):
        resolve_pinned_model(
            str(model), revision=None, expected_sha256=WEIGHTS_HASH, cache_dir=tmp_path
        )
    resolved = resolve_pinned_model(
        str(model), revision="ft-1", expected_sha256=WEIGHTS_HASH, cache_dir=tmp_path
    )
    assert resolved.path == model and resolved.revision == "ft-1"
    with pytest.raises(PinMismatchError):
        resolve_pinned_model(
            str(model), revision="ft-1", expected_sha256="2" * 64, cache_dir=tmp_path
        )


def test_sha256_configuration_is_validated() -> None:
    assert sha256_hex(None, "X") is None
    assert sha256_hex("  ", "X") is None
    assert sha256_hex(WEIGHTS_HASH.upper(), "X") == WEIGHTS_HASH
    with pytest.raises(PinError, match="64 hexadecimal"):
        sha256_hex("abc", "EMBEDDING_WEIGHTS_SHA256")
