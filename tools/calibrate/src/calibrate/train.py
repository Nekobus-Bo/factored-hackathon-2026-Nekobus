"""Train a fine-tuned decision model and write a pinned directory (ADR-0014).

The decision-points harness does not fine-tune anything but ``tfidf_lr``: a candidate
is trained first, pinned, and only then calibrated (ADR-0012, action item 3). This
command is that first step for ``hf_seqcls``:

1. checks that the schema's intent order is the contract's ``Intent`` order (the
   head's ids follow it);
2. trains with ``HFSequenceClassifierAdapter.fit`` (the lab notebook's loop, MPS when
   available);
3. re-scores validation on CPU at the serving length and fails when a locale falls
   below its floor in ``gate.min_accuracy``;
4. saves model and tokenizer into a staging directory, writes the manifest, verifies
   it, and only then replaces ``out``;
5. prints the pins to copy into the calibration config.

    make train-encoder CONFIG=tools/calibrate/configs/train_intent_distilbert.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from contracts.labels import Intent
from encoder.models import DecisionExample
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class Hyperparameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    epochs: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    learning_rate: float = Field(gt=0)
    seed: int = 0


class Gate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_accuracy: dict[str, float] = Field(
        default_factory=dict, description="Validation accuracy floor per locale"
    )


class TrainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str = "hf_seqcls"
    base_model: str
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    schema_path: Path = Field(alias="schema")
    data: dict[str, Path]
    out: Path
    hyperparameters: Hyperparameters
    train_max_length: int = Field(ge=8)
    max_length: int = Field(ge=8)
    score_batch_size: int = Field(default=64, ge=1)
    train_device: str | None = Field(
        default=None, description="None: MPS when available, else CPU"
    )
    gate: Gate = Field(default_factory=Gate)


class TrainError(RuntimeError):
    """The run cannot produce a model that may be pinned. The message says why."""


def load_config(path: Path) -> TrainConfig:
    return TrainConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def schema_labels(schema_path: Path) -> list[str]:
    """Intent names in schema order; they must equal the contract's ``Intent``."""
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    labels = [intent["name"] for intent in schema["intents"]]
    contract = [intent.value for intent in Intent]
    if labels != contract:
        raise TrainError(
            f"{schema_path} lists the intents {labels}, the contract has {contract}: "
            "run `make generate-labels` so the head's ids follow the contract"
        )
    return labels


def read_examples(path: Path) -> list[DecisionExample]:
    if not path.is_file():
        raise TrainError(f"{path} is missing: run `make pool-data-regional` first")
    lines = path.read_text(encoding="utf-8").splitlines()
    return [DecisionExample(**json.loads(line)) for line in lines if line.strip()]


def group_key(example: DecisionExample) -> str:
    return example.locale or example.lang


def validation_metrics(
    examples: list[DecisionExample], predicted: list[str]
) -> dict[str, dict[str, float]]:
    from sklearn.metrics import accuracy_score, f1_score

    groups: dict[str, list[int]] = {}
    for i, example in enumerate(examples):
        groups.setdefault(group_key(example), []).append(i)
    groups["all"] = list(range(len(examples)))
    metrics: dict[str, dict[str, float]] = {}
    for key, idx in groups.items():
        truth = [examples[i].intent for i in idx]
        pred = [predicted[i] for i in idx]
        metrics[key] = {
            "rows": float(len(idx)),
            "accuracy": round(float(accuracy_score(truth, pred)), 4),
            "macro_f1": round(
                float(f1_score(truth, pred, average="macro", zero_division=0)), 4
            ),
        }
    return metrics


def check_gate(metrics: dict[str, dict[str, float]], gate: Gate) -> list[str]:
    failures = []
    for key, floor in gate.min_accuracy.items():
        got = metrics.get(key, {}).get("accuracy")
        if got is None:
            failures.append(f"{key}: no validation rows")
        elif got < floor:
            failures.append(f"{key}: accuracy {got:.3f} < {floor:.3f}")
    return failures


def file_record(path: Path, split: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": path.as_posix(),
        "split": split,
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": sum(1 for line in data.decode("utf-8").splitlines() if line.strip()),
    }


def environment(device: str) -> dict[str, str]:
    import tokenizers
    import torch
    import transformers

    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "tokenizers": tokenizers.__version__,
        "train_device": device,
        "platform": f"{platform.system()}-{platform.machine()}",
    }


def train(config: TrainConfig) -> dict[str, str]:
    import torch
    from encoder.adapters.hf_seqcls import HFSequenceClassifierAdapter
    from encoder.weights import pins, verify_manifest, write_manifest

    labels = schema_labels(config.schema_path)
    train_rows = read_examples(config.data["train"])
    validation_rows = read_examples(config.data["validation"])
    device = config.train_device or (
        "mps" if torch.backends.mps.is_available() else "cpu"
    )
    hp = config.hyperparameters
    adapter = HFSequenceClassifierAdapter(
        name=config.name,
        labels=labels,
        max_length=config.max_length,
        train_max_length=config.train_max_length,
        batch_size=config.score_batch_size,
        base_model=config.base_model,
        base_revision=config.base_revision,
        seed=hp.seed,
        train_device=device,
    )
    started = time.perf_counter()
    logger.info("training %s on %d rows (%s)", config.name, len(train_rows), device)
    adapter.fit(
        train_rows,
        epochs=hp.epochs,
        batch_size=hp.batch_size,
        learning_rate=hp.learning_rate,
    )
    logger.info(
        "trained in %.0f s; scoring validation on CPU", time.perf_counter() - started
    )
    predicted = [p.intent for p in adapter.predict([e.text for e in validation_rows])]
    metrics = validation_metrics(validation_rows, predicted)
    for key, values in metrics.items():
        logger.info("validation %-6s %s", key, values)
    failures = check_gate(metrics, config.gate)
    if failures:
        raise TrainError("validation gate failed: " + "; ".join(failures))

    staging = config.out.with_name(config.out.name + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    adapter.save(staging)
    for path in staging.iterdir():
        path.chmod(0o644)  # readable by the image's non-root user
    write_manifest(
        staging,
        name=config.name,
        kind=config.kind,
        base_model=config.base_model,
        base_revision=config.base_revision,
        labels=labels,
        max_length=config.max_length,
        train_max_length=config.train_max_length,
        hyperparameters={
            **hp.model_dump(),
            "optimizer": "AdamW",
            "scheduler": "none",
            "score_batch_size": config.score_batch_size,
        },
        data=[file_record(path, split) for split, path in config.data.items()],
        environment=environment(device),
        metrics={f"validation/{k}": v for k, v in metrics.items()},
    )
    verify_manifest(staging)
    shutil.rmtree(config.out, ignore_errors=True)
    staging.rename(config.out)
    return pins(config.out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and pin a decision model")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        config = load_config(args.config)
        pinned = train(config)
    except TrainError as exc:
        print(f"train: {exc}", file=sys.stderr)
        return 1
    print(f"\nwrote {config.out}")
    print("pins for the calibration config (backends.<id>):")
    print(f"  revision: {pinned['revision']}")
    print(f"  weights_sha256: {pinned['weights_sha256']}")
    print(
        f"  params: {{model: {config.out.as_posix()}, max_length: {config.max_length}}}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
