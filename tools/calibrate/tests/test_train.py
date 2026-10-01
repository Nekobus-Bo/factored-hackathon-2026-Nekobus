"""Training command for fine-tuned decision models (ADR-0014).

The pure parts (schema order, the per-locale gate, metrics) run anywhere; the end-to-end
run trains a tiny random DistilBERT on CPU and checks the pinned directory it writes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from calibrate.train import (
    Gate,
    TrainConfig,
    TrainError,
    check_gate,
    schema_labels,
    validation_metrics,
)
from contracts.labels import Intent
from encoder.models import DecisionExample

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA = REPO_ROOT / "data" / "eval" / "synthetic" / "schema.yaml"
LABELS = [i.value for i in Intent]


def _example(
    i: int, intent: str, locale: str | None, lang: str = "es"
) -> DecisionExample:
    return DecisionExample(
        id=f"r{i}",
        text=f"texto {i}",
        lang=lang,
        locale=locale,
        intent=intent,
        split="validation",
    )


def test_the_committed_schema_follows_the_contract_order() -> None:
    assert schema_labels(SCHEMA) == LABELS


def test_a_reordered_schema_is_refused(tmp_path: Path) -> None:
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    schema["intents"] = list(reversed(schema["intents"]))
    path = tmp_path / "schema.yaml"
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    with pytest.raises(TrainError, match="make generate-labels"):
        schema_labels(path)


def test_metrics_group_by_locale_then_language() -> None:
    rows = [
        _example(0, "greeting", "es-MX"),
        _example(1, "deny", "es-MX"),
        _example(2, "greeting", None, lang="en"),
    ]
    metrics = validation_metrics(rows, ["greeting", "greeting", "greeting"])
    assert metrics["es-MX"]["accuracy"] == 0.5
    assert metrics["en"]["accuracy"] == 1.0
    assert metrics["all"]["rows"] == 3


def test_the_gate_names_every_locale_below_its_floor() -> None:
    metrics = {"es-MX": {"accuracy": 0.8}, "pt-BR": {"accuracy": 0.95}}
    failures = check_gate(
        metrics, Gate(min_accuracy={"es-MX": 0.85, "pt-BR": 0.85, "es-AR": 0.85})
    )
    assert failures == ["es-MX: accuracy 0.800 < 0.850", "es-AR: no validation rows"]


def test_the_committed_config_loads() -> None:
    path = (
        REPO_ROOT / "tools" / "calibrate" / "configs" / "train_intent_distilbert.yaml"
    )
    config = TrainConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    assert config.max_length == 256 and config.train_max_length == 128
    assert config.hyperparameters.epochs == 4


def _tiny_base(directory: Path) -> Path:
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    directory.mkdir(parents=True)
    vocab = directory.parent / "vocab.txt"
    vocab.write_text(
        "\n".join(["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "hola", "tarjeta"])
    )
    torch.manual_seed(0)
    config = transformers.DistilBertConfig(
        vocab_size=7,
        dim=16,
        n_layers=1,
        n_heads=2,
        hidden_dim=32,
        max_position_embeddings=64,
    )
    transformers.DistilBertForSequenceClassification(config).save_pretrained(directory)
    transformers.DistilBertTokenizerFast(vocab_file=str(vocab)).save_pretrained(
        directory
    )
    return directory


def test_a_run_writes_a_verified_pinned_directory(tmp_path: Path) -> None:
    from calibrate.train import train
    from encoder.weights import verify_manifest

    base = _tiny_base(tmp_path / "base")
    rows = [
        {"id": f"r{i}", "text": "hola tarjeta", "lang": "es", "locale": "es-MX",
         "intent": LABELS[i % len(LABELS)], "split": split}
        for split in ("train", "validation") for i in range(20)
    ]  # fmt: skip
    for split in ("train", "validation"):
        (tmp_path / f"{split}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows if r["split"] == split),
            encoding="utf-8",
        )
    out = tmp_path / "weights" / "tiny"
    out.mkdir(parents=True)
    (out / "stale.bin").write_bytes(b"old run")  # replaced, never merged
    config = TrainConfig.model_validate(
        {
            "name": "tiny",
            "base_model": str(base),
            "base_revision": "0" * 40,
            "schema": str(SCHEMA),
            "data": {s: str(tmp_path / f"{s}.jsonl") for s in ("train", "validation")},
            "out": str(out),
            "hyperparameters": {"epochs": 1, "batch_size": 8, "learning_rate": 5e-5},
            "train_max_length": 16,
            "max_length": 32,
            "train_device": "cpu",
        }
    )
    pinned = train(config)
    manifest = verify_manifest(out)
    assert not (out / "stale.bin").exists()
    assert pinned["revision"] == manifest.revision_label()
    assert manifest.labels == LABELS and manifest.max_length == 32
    assert {d.split for d in manifest.data} == {"train", "validation"}
    assert "validation/es-MX" in manifest.metrics


def test_a_run_below_the_gate_pins_nothing(tmp_path: Path) -> None:
    from calibrate.train import train

    base = _tiny_base(tmp_path / "base")
    rows = [{"id": "r", "text": "hola", "lang": "es", "locale": "es-MX",
             "intent": "greeting", "split": "train"}]  # fmt: skip
    for split in ("train", "validation"):
        (tmp_path / f"{split}.jsonl").write_text(
            json.dumps(rows[0]) + "\n", encoding="utf-8"
        )
    config = TrainConfig.model_validate(
        {
            "name": "tiny",
            "base_model": str(base),
            "base_revision": "0" * 40,
            "schema": str(SCHEMA),
            "data": {s: str(tmp_path / f"{s}.jsonl") for s in ("train", "validation")},
            "out": str(tmp_path / "out"),
            "hyperparameters": {"epochs": 1, "batch_size": 1, "learning_rate": 5e-5},
            "train_max_length": 16,
            "max_length": 32,
            "train_device": "cpu",
            "gate": {"min_accuracy": {"es-AR": 0.5}},
        }
    )
    with pytest.raises(TrainError, match="es-AR: no validation rows"):
        train(config)
    assert not (tmp_path / "out").exists()
