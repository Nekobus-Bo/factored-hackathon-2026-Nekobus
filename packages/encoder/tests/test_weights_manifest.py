"""The manifest of a trained model directory (ADR-0014, Appendix A). No PyTorch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from encoder.pinning import PinMismatchError
from encoder.weights import (
    MANIFEST_NAME,
    ManifestError,
    main,
    pins,
    verify_manifest,
    write_manifest,
)

from .tiny_hf import manifest_fields


def _fake_model_dir(directory: Path) -> Path:
    """The files a saved classifier holds; their content does not matter here."""
    directory.mkdir(parents=True)
    for name, content in {
        "config.json": '{"model_type": "distilbert"}',
        "model.safetensors": "weights",
        "tokenizer.json": "{}",
        "tokenizer_config.json": "{}",
    }.items():
        (directory / name).write_text(content, encoding="utf-8")
    return directory


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    directory = _fake_model_dir(tmp_path / "model")
    write_manifest(directory, **manifest_fields())
    return directory


def test_a_fresh_manifest_verifies_and_pins_the_whole_directory(
    model_dir: Path,
) -> None:
    manifest = verify_manifest(model_dir)
    pinned = pins(model_dir)
    assert set(manifest.files) == {
        "config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"
    }  # fmt: skip
    assert pinned["revision"] == f"tiny-intent:{manifest.sha256()[:12]}"
    assert pinned["weights_sha256"] == manifest.files["model.safetensors"]


def test_the_revision_label_moves_when_anything_in_the_manifest_changes(
    tmp_path: Path,
) -> None:
    a = write_manifest(_fake_model_dir(tmp_path / "a"), **manifest_fields())
    b = write_manifest(
        _fake_model_dir(tmp_path / "b"),
        **manifest_fields(hyperparameters={"epochs": 2}),
    )
    assert a.files == b.files
    assert a.revision_label() != b.revision_label()


@pytest.mark.parametrize("name", ["tokenizer.json", "config.json", "model.safetensors"])
def test_a_changed_file_fails_verification(model_dir: Path, name: str) -> None:
    (model_dir / name).write_text("tampered", encoding="utf-8")
    with pytest.raises(ManifestError, match=name):
        verify_manifest(model_dir)


def test_a_manifest_error_is_a_pin_mismatch(model_dir: Path) -> None:
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PinMismatchError):  # the service's ALLOW_STALE handles it alike
        verify_manifest(model_dir)


@pytest.mark.parametrize(
    "stray", ["pytorch_model.bin", "training_args.bin", ".DS_Store"]
)
def test_a_file_outside_the_allowlist_fails(model_dir: Path, stray: str) -> None:
    (model_dir / stray).write_bytes(b"x")
    with pytest.raises(ManifestError, match="not allowed"):
        verify_manifest(model_dir)


def test_a_missing_manifest_fails(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="no manifest.json"):
        verify_manifest(_fake_model_dir(tmp_path / "bare"))


def test_an_edited_manifest_fails_validation(model_dir: Path) -> None:
    raw = json.loads((model_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    raw["unexpected"] = True
    (model_dir / MANIFEST_NAME).write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ManifestError, match="invalid manifest"):
        verify_manifest(model_dir)


def test_a_file_listed_but_gone_fails(model_dir: Path) -> None:
    (model_dir / "tokenizer.json").unlink()
    with pytest.raises(ManifestError, match="missing"):
        verify_manifest(model_dir)


def test_the_base_revision_must_be_a_commit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="base_revision"):
        write_manifest(
            _fake_model_dir(tmp_path / "m"), **manifest_fields(base_revision="main")
        )


def test_the_cli_verifies_and_fails_loudly(
    model_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["verify", str(model_dir)]) == 0
    assert "OK tiny-intent:" in capsys.readouterr().out
    (model_dir / "vocab.txt").write_text("extra", encoding="utf-8")
    assert main(["verify", str(model_dir)]) == 1
    assert "FAIL" in capsys.readouterr().err
