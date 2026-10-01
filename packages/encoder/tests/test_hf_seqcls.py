"""The ``hf_seqcls`` adapter and its registry entry, on a tiny random model (ADR-0014).

The generic checklist (distribution, determinism, no text in logs) runs in
``test_adapter_conformance.py``; this module covers what is specific to a fine-tuned
directory: the pin chain, label drift and training.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("torch")
pytest.importorskip("transformers")

from encoder import registry  # noqa: E402
from encoder.adapters.hf_seqcls import HFSequenceClassifierAdapter  # noqa: E402
from encoder.decision_points import BackendSpec  # noqa: E402
from encoder.models import DecisionExample  # noqa: E402
from encoder.pinning import PinMismatchError  # noqa: E402
from encoder.registry import BackendBuildError  # noqa: E402

from .tiny_hf import (  # noqa: E402
    LABELS,
    backend_spec_dict,
    build_model_dir,
    build_pinned_dir,
)

TEXTS = ["me robaron la tarjeta", "não reconheço a compra", "yes please block it"]


@pytest.fixture(scope="module")
def pinned_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_pinned_dir(tmp_path_factory.mktemp("hf") / "tiny-intent")


def _spec(directory: Path, **changes: object) -> BackendSpec:
    raw = backend_spec_dict(directory)
    raw.update(changes)
    return BackendSpec.model_validate(raw)


def test_the_registry_builds_a_pinned_directory(pinned_dir: Path) -> None:
    adapter = registry.build(_spec(pinned_dir))
    assert isinstance(adapter, HFSequenceClassifierAdapter)
    assert adapter.classes_ == LABELS
    predictions = adapter.predict(TEXTS)
    assert [len(p.probabilities) for p in predictions] == [len(LABELS)] * len(TEXTS)
    for p in predictions:
        assert sum(p.probabilities.values()) == pytest.approx(1.0, abs=1e-9)
        assert p.confidence == max(p.probabilities.values())


def test_the_model_id_carries_the_weights_hash(pinned_dir: Path) -> None:
    spec = _spec(pinned_dir)
    assert spec.model_id == f"hf_seqcls:tiny-intent@sha256:{spec.weights_sha256[:12]}"


def test_a_wrong_weights_pin_stops_the_backend(pinned_dir: Path) -> None:
    with pytest.raises(PinMismatchError, match="weights SHA-256"):
        registry.build(_spec(pinned_dir, weights_sha256="0" * 64))


def test_a_revision_from_another_manifest_stops_the_backend(pinned_dir: Path) -> None:
    with pytest.raises(PinMismatchError, match="revision"):
        registry.build(_spec(pinned_dir, revision="tiny-intent:000000000000"))


def test_a_wrong_model_id_stops_the_backend(pinned_dir: Path) -> None:
    with pytest.raises(PinMismatchError, match="model_id"):
        registry.build(
            _spec(pinned_dir, model_id="hf_seqcls:other@sha256:000000000000")
        )


def test_labels_in_another_order_are_label_drift(pinned_dir: Path) -> None:
    with pytest.raises(BackendBuildError, match="label drift"):
        registry.build(_spec(pinned_dir, labels=list(reversed(LABELS))))


def test_a_max_length_other_than_the_calibrated_one_is_refused(
    pinned_dir: Path,
) -> None:
    raw_params = {"model": str(pinned_dir), "max_length": 32}
    with pytest.raises(BackendBuildError, match="max_length"):
        registry.build(_spec(pinned_dir, params=raw_params))


def test_a_missing_directory_is_a_build_error(tmp_path: Path, pinned_dir: Path) -> None:
    raw_params = {"model": str(tmp_path / "absent")}
    with pytest.raises(BackendBuildError, match="not a directory"):
        registry.build(_spec(pinned_dir, params=raw_params))


def test_a_tampered_tokenizer_stops_the_backend(tmp_path: Path) -> None:
    directory = build_pinned_dir(tmp_path / "tiny-intent")
    spec = _spec(directory)
    config = json.loads(
        (directory / "tokenizer_config.json").read_text(encoding="utf-8")
    )
    config["model_max_length"] = 7
    (directory / "tokenizer_config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    with pytest.raises(PinMismatchError, match="tokenizer_config.json"):
        registry.build(spec)


def test_the_adapter_refuses_a_head_in_another_order(tmp_path: Path) -> None:
    directory = build_model_dir(tmp_path / "m", labels=list(reversed(LABELS)))
    with pytest.raises(ValueError, match="label drift"):
        HFSequenceClassifierAdapter(labels=LABELS, max_length=64).load(directory)


def test_fit_trains_saves_and_reloads(tmp_path: Path) -> None:
    base = build_model_dir(tmp_path / "base")
    rows = [
        DecisionExample(id=f"r{i}", text=text, lang="es", intent=intent, split="train")
        for i, (text, intent) in enumerate(
            [(TEXTS[0], "report_stolen_card"), (TEXTS[1], "report_unrecognized_charge"),
             (TEXTS[2], "request_card_block"), ("hola", "greeting")] * 2
        )
    ]  # fmt: skip
    adapter = HFSequenceClassifierAdapter(
        labels=LABELS,
        max_length=64,
        train_max_length=32,
        base_model=str(base),
        base_revision="0" * 40,
        train_device="cpu",
    )
    adapter.fit(rows, epochs=1, batch_size=4)
    before = adapter.predict(TEXTS)
    adapter.save(tmp_path / "trained")
    reloaded = HFSequenceClassifierAdapter(labels=LABELS, max_length=64)
    reloaded.load(tmp_path / "trained")
    after = reloaded.predict(TEXTS)
    assert [p.intent for p in before] == [p.intent for p in after]
    for b, a in zip(before, after, strict=True):
        assert a.confidence == pytest.approx(b.confidence, abs=1e-6)


def test_fit_refuses_labels_outside_the_space(tmp_path: Path) -> None:
    adapter = HFSequenceClassifierAdapter(
        labels=LABELS, base_model="unused", base_revision="0" * 40
    )
    row = DecisionExample(
        id="x", text="x", lang="es", intent="not_an_intent", split="train"
    )
    with pytest.raises(ValueError, match="outside the label space"):
        adapter.fit([row])
