"""A tiny ``hf_seqcls`` model directory built on the fly (a few KB, random weights).

Tests of the adapter, the manifest and the registry use it, so none of them needs the
real weights, the network or a GPU.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from contracts.labels import Intent

LABELS = [intent.value for intent in Intent]
NAME = "tiny-intent"
BASE_REVISION = "0" * 40
MAX_LENGTH = 64  # the tiny model has 64 positions
_VOCAB = [
    "[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]",
    "me", "robaron", "la", "tarjeta", "não", "reconheço", "compra", "yes", "please",
    "block", "it", "hola", "sí", "no", "saldo", "##s", "##a", "##o", "(", ")", "-",
]  # fmt: skip


def build_model_dir(
    directory: Path, *, labels: list[str] | None = None, seed: int = 0
) -> Path:
    """Write a randomly initialized DistilBERT classifier and its tokenizer."""
    import torch
    from transformers import (
        DistilBertConfig,
        DistilBertForSequenceClassification,
        DistilBertTokenizerFast,
    )

    labels = list(labels or LABELS)
    directory.mkdir(parents=True, exist_ok=True)
    vocab = directory.parent / f"{directory.name}.vocab.txt"  # outside the model dir
    vocab.write_text("\n".join(_VOCAB) + "\n", encoding="utf-8")
    torch.manual_seed(seed)
    config = DistilBertConfig(
        vocab_size=len(_VOCAB),
        dim=16,
        n_layers=1,
        n_heads=2,
        hidden_dim=32,
        max_position_embeddings=MAX_LENGTH,
        num_labels=len(labels),
        id2label=dict(enumerate(labels)),
        label2id={label: i for i, label in enumerate(labels)},
    )
    DistilBertForSequenceClassification(config).save_pretrained(directory)
    DistilBertTokenizerFast(vocab_file=str(vocab)).save_pretrained(directory)
    return directory


def manifest_fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "name": NAME,
        "kind": "hf_seqcls",
        "base_model": "tiny/base",
        "base_revision": BASE_REVISION,
        "labels": list(LABELS),
        "max_length": MAX_LENGTH,
        "train_max_length": 32,
        "hyperparameters": {
            "epochs": 1,
            "batch_size": 4,
            "learning_rate": 5e-5,
            "seed": 0,
        },
        "data": [],
        "environment": {"torch": "test", "transformers": "test"},
    }
    fields.update(overrides)
    return fields


def build_pinned_dir(directory: Path, **manifest_overrides: Any) -> Path:
    """A tiny model directory with its manifest, ready for ``registry.build``."""
    from encoder.weights import write_manifest

    build_model_dir(directory, labels=manifest_overrides.get("labels"))
    write_manifest(directory, **manifest_fields(**manifest_overrides))
    return directory


def backend_spec_dict(directory: Path) -> dict[str, Any]:
    """The artifact backend entry that pins ``directory``."""
    from encoder.registry import hf_seqcls_model_id
    from encoder.weights import pins, verify_manifest

    manifest = verify_manifest(directory)
    pinned = pins(directory)
    return {
        "kind": "hf_seqcls",
        "model_id": hf_seqcls_model_id(manifest.name, pinned["weights_sha256"]),
        "revision": pinned["revision"],
        "weights_sha256": pinned["weights_sha256"],
        "probability_kind": "distribution",
        "labels": list(manifest.labels),
        "local_only": True,
        "timeout_ms": 1000,
        "params": {"model": str(directory), "max_length": manifest.max_length},
    }
