from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import torch

from encoder.base import DecisionAdapter
from encoder.models import DecisionExample, DecisionPrediction, Slot

logger = logging.getLogger(__name__)


class GLiNERAdapter(DecisionAdapter):
    """GLiNER / GLiNER2 adapter for zero-shot intent classification
    and slot extraction.

    `probabilities` is not a distribution: the top label carries its confidence and
    the rest share what is left uniformly. So this adapter is `top1_only`: a plain
    threshold on the top confidence, no calibrator, no group view.
    """

    kind = "gliner"
    probability_kind = "top1_only"

    def __init__(
        self,
        model_id: str = "fastino/gliner2.5-multi-v1",
        name: str | None = None,
        device: str = "cpu",
    ) -> None:
        self.model_id = model_id
        self.name = name or model_id.split("/")[-1]
        self.device = device
        self.model: Any = None
        self._is_gliner2: bool = False
        self._load_model()

    def _load_model(self) -> None:
        """Load GLiNER model using gliner2 or gliner depending on architecture."""
        errors: list[str] = []
        try:
            from gliner2 import AutoExtractor

            logger.info(
                "Attempting to load %s with gliner2 AutoExtractor", self.model_id
            )
            self.model = AutoExtractor.from_pretrained(self.model_id)
            if hasattr(self.model, "to"):
                self.model.to(self.device)
            self._is_gliner2 = True
            return
        except Exception as exc:
            errors.append(f"gliner2: {exc}")
            logger.debug("gliner2 load failed (%s), falling back to gliner", exc)

        try:
            from gliner import GLiNER

            logger.info("Loading %s with gliner GLiNER", self.model_id)
            self.model = GLiNER.from_pretrained(self.model_id)
            if hasattr(self.model, "to"):
                self.model.to(self.device)
            self._is_gliner2 = False
            return
        except Exception as exc:
            errors.append(f"gliner: {exc}")
            logger.warning("Could not load GLiNER model %s: %s", self.model_id, exc)

        self.model = None
        raise RuntimeError(
            f"Could not load GLiNER model '{self.model_id}': {'; '.join(errors)}"
        )

    def fit(
        self,
        train_examples: Sequence[DecisionExample],
        val_examples: Sequence[DecisionExample] | None = None,
        epochs: int = 2,
        batch_size: int = 4,
        learning_rate: float = 5e-5,
    ) -> None:
        """Fine-tune the encoder model on domain examples using MPS when available."""
        if self.model is None:
            raise RuntimeError("Cannot fine-tune: underlying model is not initialized")

        if not self._is_gliner2:
            raise NotImplementedError(
                "GLiNER v1 models do not support fine-tuning for intent classification"
            )

        train_device = "mps" if torch.backends.mps.is_available() else "cpu"
        logger.info(
            "Fine-tuning GLiNER adapter %s on device: %s "
            "(%d epochs, batch_size=%d, lr=%s)",
            self.name,
            train_device,
            epochs,
            batch_size,
            learning_rate,
        )

        train_data = []
        for e in train_examples:
            entities_dict: dict[str, list[str]] = {}
            for s in e.slots:
                entities_dict.setdefault(s.type, []).append(s.value)
            schema = {"intent": e.intent, "entities": entities_dict}
            train_data.append((e.text, schema))

        if not train_data:
            raise ValueError("No training examples provided for fine-tuning")

        try:
            self.model.to(train_device)
            self.model.train()

            trainable_params = [p for p in self.model.parameters() if p.requires_grad]
            if not trainable_params:
                raise RuntimeError("No trainable parameters found in model")

            optimizer = torch.optim.AdamW(trainable_params, lr=learning_rate)
            total_samples = len(train_data)
            num_batches = (total_samples + batch_size - 1) // batch_size

            for epoch in range(epochs):
                epoch_loss = 0.0
                for batch_idx in range(0, total_samples, batch_size):
                    batch_samples = train_data[batch_idx : batch_idx + batch_size]
                    step = batch_idx // batch_size + 1
                    batch = self.model.processor.collate_fn_train(
                        batch_samples, architecture=self.model.architecture
                    )
                    batch = batch.to(train_device)
                    optimizer.zero_grad()
                    output = self.model(batch)
                    loss = output.loss
                    loss.backward()
                    optimizer.step()

                    batch_loss = float(loss.item())
                    epoch_loss += batch_loss * len(batch_samples)
                    logger.info(
                        "Epoch %d/%d - step %d/%d (device: %s) - batch loss: %.4f",
                        epoch + 1,
                        epochs,
                        step,
                        num_batches,
                        train_device,
                        batch_loss,
                    )

                avg_epoch_loss = epoch_loss / max(1, total_samples)
                logger.info(
                    "Epoch %d/%d completed (device: %s) - average loss: %.4f",
                    epoch + 1,
                    epochs,
                    train_device,
                    avg_epoch_loss,
                )
        finally:
            if hasattr(self.model, "eval"):
                self.model.eval()
            if hasattr(self.model, "to"):
                self.model.to(self.device)

    def predict(
        self,
        texts: Sequence[str],
        candidate_intents: Sequence[str] | None = None,
        candidate_slots: Sequence[str] | None = None,
    ) -> list[DecisionPrediction]:
        """Predict intent and extract slots for input texts on CPU."""
        if not texts:
            return []

        if self.model is None:
            raise RuntimeError("Cannot predict: GLiNER model is not loaded")

        if not self._is_gliner2:
            raise NotImplementedError(
                "GLiNER v1 models do not support intent classification; "
                "use gliner2 models"
            )

        intents_list = list(candidate_intents) if candidate_intents else ["unknown"]
        slots_list = list(candidate_slots) if candidate_slots else []

        # Inference strictly on CPU
        if hasattr(self.model, "eval"):
            self.model.eval()
        if hasattr(self.model, "to"):
            self.model.to("cpu")

        schema = self.model.create_schema()
        if intents_list:
            schema.classification("intent", intents_list)
        if slots_list:
            schema.entities(slots_list)

        predictions: list[DecisionPrediction] = []
        for text in texts:
            res = self.model.extract(
                text,
                schema,
                include_confidence=True,
                include_spans=True,
            )
            if not isinstance(res, dict) or "intent" not in res:
                raise RuntimeError(
                    f"gliner2 output lacks 'intent' field for text: {text!r}"
                )
            intent_data = res["intent"]
            if not isinstance(intent_data, dict):
                raise RuntimeError(
                    f"gliner2 output 'intent' must be a dict for text: {text!r}"
                )
            if "label" not in intent_data:
                raise RuntimeError(
                    f"gliner2 output lacks 'intent.label' for text: {text!r}"
                )
            if "confidence" not in intent_data:
                raise RuntimeError(
                    f"gliner2 output lacks 'intent.confidence' for text: {text!r}"
                )

            pred_intent = str(intent_data["label"])
            confidence = float(intent_data["confidence"])

            extracted_slots: list[Slot] = []
            entities_data = res.get("entities", {})
            for slot_type, entity_items in entities_data.items():
                for item in entity_items:
                    extracted_slots.append(
                        Slot(
                            type=str(slot_type),
                            value=str(item.get("text", "")),
                            start=int(item.get("start", 0)),
                            end=int(item.get("end", 0)),
                        )
                    )

            prob_map = {pred_intent: confidence}
            for intent in intents_list:
                if intent not in prob_map:
                    prob_map[intent] = (1.0 - confidence) / max(
                        1, len(intents_list) - 1
                    )

            predictions.append(
                DecisionPrediction(
                    intent=pred_intent,
                    confidence=confidence,
                    slots=extracted_slots,
                    probabilities=prob_map,
                )
            )

        return predictions

    def save(self, path: str | Path) -> None:
        """Save model or adapter weights to directory."""
        target_dir = Path(path)
        target_dir.mkdir(parents=True, exist_ok=True)
        if self.model is not None and hasattr(self.model, "save_pretrained"):
            self.model.save_pretrained(str(target_dir))
        else:
            raise RuntimeError(f"Model {self.name} does not support save_pretrained")

    def load(self, path: str | Path) -> None:
        """Load model weights from directory."""
        target_dir = Path(path)
        if not target_dir.exists() or not target_dir.is_dir():
            raise FileNotFoundError(f"Weights directory not found: {target_dir}")
        expected_files = ["config.json", "model.safetensors", "pytorch_model.bin"]
        if not any((target_dir / fname).exists() for fname in expected_files):
            raise FileNotFoundError(
                f"Weights directory {target_dir} is missing model artifacts "
                f"(expected one of {expected_files})"
            )
        self.model_id = str(target_dir)
        self._load_model()
