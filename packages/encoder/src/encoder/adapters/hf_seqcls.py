"""Fine-tuned sequence classifier (registry kind ``hf_seqcls``, ADR-0014).

A Hugging Face encoder with a classification head over a fixed label space: the
pooled pt-BR / es-MX / es-AR DistilBERT of
``reports/intent-models-regional-datasets.md``. ``fit`` reproduces the lab notebook
(``lab/notebooks/finetune__decision-pooled.py``) step for step, so a model trained
here is the model the report measured:

* the seed is set before the base model loads (the new head's initialization draws
  from it), then batches come from ``torch.randperm`` over the whole train split;
* AdamW, no scheduler, no warmup, no class weights;
* training truncates at ``train_max_length`` (128) and scoring at ``max_length`` (256),
  the lengths the report used.

Training may use MPS (ADR-0010 §3); ``predict`` always runs on CPU (ADR-0008).
Weights load only from a local directory, only as safetensors, never with remote
code. Nothing here logs customer text.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from encoder.base import DecisionAdapter, ProbabilityKind
from encoder.models import DecisionExample, DecisionPrediction

logger = logging.getLogger(__name__)


class HFSequenceClassifierAdapter(DecisionAdapter):
    """A fine-tuned encoder whose softmax is a distribution over ``labels``."""

    kind: ClassVar[str] = "hf_seqcls"
    probability_kind: ClassVar[ProbabilityKind] = "distribution"

    def __init__(
        self,
        name: str = "hf_seqcls",
        *,
        labels: Sequence[str] | None = None,
        max_length: int = 256,
        train_max_length: int = 128,
        batch_size: int = 64,
        base_model: str | None = None,
        base_revision: str | None = None,
        seed: int = 0,
        train_device: str | None = None,
    ) -> None:
        self.name = name
        self.labels: list[str] = list(labels or [])
        self.max_length = max_length
        self.train_max_length = train_max_length
        self.batch_size = batch_size
        self.base_model = base_model
        self.base_revision = base_revision
        self.seed = seed
        self.train_device = train_device
        self._model: Any = None
        self._tokenizer: Any = None

    @property
    def classes_(self) -> list[str]:
        """The label space, in the head's id order (as ``tfidf_lr`` exposes it)."""
        return list(self.labels)

    # --- training ---

    def fit(
        self,
        train_examples: Sequence[DecisionExample],
        val_examples: Sequence[DecisionExample] | None = None,
        epochs: int = 4,
        batch_size: int = 32,
        learning_rate: float = 5e-5,
    ) -> None:
        """Fine-tune ``base_model`` on ``train_examples`` (the notebook's loop)."""
        if not self.base_model or not self.base_revision:
            raise ValueError("hf_seqcls: fit needs base_model and base_revision")
        if not self.labels:
            raise ValueError("hf_seqcls: fit needs the label space (labels=...)")
        label2id = {label: i for i, label in enumerate(self.labels)}
        unknown = {e.intent for e in train_examples} - set(label2id)
        if unknown:
            raise ValueError(
                f"hf_seqcls: train labels outside the label space: {sorted(unknown)}"
            )
        device = self.train_device or (
            "mps" if torch.backends.mps.is_available() else "cpu"
        )

        tokenizer = AutoTokenizer.from_pretrained(
            self.base_model, revision=self.base_revision
        )
        torch.manual_seed(self.seed)
        model = AutoModelForSequenceClassification.from_pretrained(
            self.base_model,
            revision=self.base_revision,
            num_labels=len(self.labels),
            label2id=label2id,
            id2label={i: label for label, i in label2id.items()},
            ignore_mismatched_sizes=True,
        ).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
        texts = [e.text for e in train_examples]
        targets = torch.tensor([label2id[e.intent] for e in train_examples])
        for epoch in range(epochs):
            model.train()
            for idx in torch.randperm(len(texts)).split(batch_size):
                batch = tokenizer(
                    [texts[i] for i in idx],
                    padding=True,
                    truncation=True,
                    max_length=self.train_max_length,
                    return_tensors="pt",
                ).to(device)
                model(**batch, labels=targets[idx].to(device)).loss.backward()
                optimizer.step()
                optimizer.zero_grad()
            logger.info(
                "hf_seqcls: epoch %d/%d done (%d rows)", epoch + 1, epochs, len(texts)
            )
        model.eval()
        self._model = model.to("cpu")
        self._tokenizer = tokenizer

    # --- inference ---

    def predict(
        self,
        texts: Sequence[str],
        candidate_intents: Sequence[str] | None = None,
        candidate_slots: Sequence[str] | None = None,
    ) -> list[DecisionPrediction]:
        """Softmax over the whole label space. The head is fixed, so
        ``candidate_intents`` is ignored (a view narrows labels downstream)."""
        if not texts:
            return []
        if self._model is None or self._tokenizer is None:
            raise RuntimeError(
                f"hf_seqcls '{self.name}' must be loaded or fitted first"
            )
        results: list[DecisionPrediction] = []
        with torch.inference_mode():
            for start in range(0, len(texts), self.batch_size):
                batch = self._tokenizer(
                    list(texts[start : start + self.batch_size]),
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                logits = self._model(**batch).logits.to(torch.float64)
                for row in torch.softmax(logits, dim=-1).tolist():
                    probs = dict(zip(self.labels, row, strict=True))
                    best = max(probs, key=probs.__getitem__)
                    results.append(
                        DecisionPrediction(
                            intent=best, confidence=probs[best], probabilities=probs
                        )
                    )
        return results

    # --- persistence ---

    def save(self, path: str | Path) -> None:
        """Write the model (safetensors) and the tokenizer. The manifest is written
        by the training command, which knows the data it trained on."""
        if self._model is None or self._tokenizer is None:
            raise RuntimeError(f"hf_seqcls '{self.name}' has nothing to save")
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        self._model.save_pretrained(target)
        self._tokenizer.save_pretrained(target)

    def load(self, path: str | Path) -> None:
        """Load a local directory on CPU; its head must match ``labels`` exactly."""
        directory = Path(path)
        model = AutoModelForSequenceClassification.from_pretrained(
            directory,
            local_files_only=True,
            use_safetensors=True,
            trust_remote_code=False,
        )
        order = [model.config.id2label[i] for i in range(model.config.num_labels)]
        if self.labels and order != self.labels:
            raise ValueError(
                f"hf_seqcls: label drift in {directory}: the head is {order}, "
                f"the artifact expects {self.labels}"
            )
        self.labels = order
        self._model = model.to("cpu").eval()
        self._tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False
        )
