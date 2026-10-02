from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np

try:
    from sentence_transformers.sentence_transformer import losses
except ImportError:
    from sentence_transformers import losses
import torch
from sentence_transformers import InputExample, SentenceTransformer
from torch.utils.data import DataLoader

from retrieval.base import RetrievalAdapter
from retrieval.models import KBSnippet, QueryExample

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "ibm-granite/granite-embedding-311m-multilingual-r2"
# Precisions the weights may load in. float32 is the default: bf16 weights (as Granite
# ships) would otherwise load as bf16, which is slow on CPUs without bf16 support.
EMBEDDING_DTYPES = ("float32", "bfloat16")
DEFAULT_EMBEDDING_DTYPE = "float32"


class SentenceTransformersAdapter(RetrievalAdapter):
    """Dense bi-encoder retrieval adapter using SentenceTransformers."""

    def __init__(
        self,
        model_id: str = DEFAULT_EMBEDDING_MODEL,
        name: str | None = None,
        device: str = "cpu",
        dtype: str = DEFAULT_EMBEDDING_DTYPE,
    ) -> None:
        if dtype not in EMBEDDING_DTYPES:
            allowed = ", ".join(EMBEDDING_DTYPES)
            raise ValueError(f"embedding dtype must be one of {allowed}, got {dtype!r}")
        self.model_id = model_id
        self.name = name or model_id.split("/")[-1]
        self.device = device
        self.dtype = dtype
        self.model: SentenceTransformer | None = None
        self.doc_ids: list[str] = []
        self.corpus_embeddings: np.ndarray | None = None
        self._load_model()

    def _load_model(self) -> None:
        """Load SentenceTransformer model on CPU."""
        try:
            logger.info(
                "Loading SentenceTransformer %s on device %s as %s",
                self.model_id,
                self.device,
                self.dtype,
            )
            self.model = SentenceTransformer(
                self.model_id,
                device=self.device,
                model_kwargs={"dtype": self.dtype},
            )
        except Exception as exc:
            self.model = None
            raise RuntimeError(
                f"Could not load SentenceTransformer '{self.model_id}': {exc}"
            ) from exc

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Unit-length float32 embeddings on CPU, one row per text.

        What ``index`` and ``search`` use, and what the model server returns from
        ``POST /v1/embed``: one function, so in-process and remote vectors are the
        same vectors.
        """
        if self.model is None:
            raise RuntimeError("SentenceTransformer model is not loaded")
        # Ensure model is on CPU for inference
        self.model.to("cpu")
        embeddings = self.model.encode(
            list(texts),
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return np.asarray(embeddings, dtype=np.float32)

    def index(self, kb: Sequence[KBSnippet]) -> None:
        """Compute and cache dense embeddings for knowledge base snippets on CPU."""
        if self.model is None:
            raise RuntimeError("SentenceTransformer model is not loaded")

        self.doc_ids = [s.id for s in kb]
        texts = [f"{s.title} {s.text}" for s in kb]

        if not texts:
            dim = self.model.get_embedding_dimension() or 0
            self.corpus_embeddings = np.empty((0, dim), dtype=np.float32)
            return

        self.corpus_embeddings = self.embed(texts)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Dense semantic search using cosine similarity on CPU."""
        if self.model is None:
            raise RuntimeError("SentenceTransformer model is not loaded")
        if self.corpus_embeddings is None or len(self.doc_ids) == 0:
            return []

        query_emb = self.embed([query])[0]

        # Dot product of normalized vectors equals cosine similarity
        scores = np.dot(self.corpus_embeddings, query_emb)
        ranked_indices = np.argsort(scores)[::-1][:top_k]

        return [(self.doc_ids[idx], float(scores[idx])) for idx in ranked_indices]

    def fit(
        self,
        queries: Sequence[QueryExample],
        kb: Sequence[KBSnippet],
        val_queries: Sequence[QueryExample] | None = None,
        epochs: int = 1,
        batch_size: int = 8,
        learning_rate: float = 2e-5,
    ) -> None:
        """Fine-tune embedding model with in-batch negatives using MPS if available."""
        if self.model is None:
            raise RuntimeError("Cannot fine-tune: model is uninitialized")

        kb_map = {s.id: f"{s.title} {s.text}" for s in kb}

        # Build positive query-passage pairs for in-batch negative ranking loss
        train_examples: list[InputExample] = []
        for q in queries:
            for rel_id in q.relevant_ids:
                if rel_id in kb_map:
                    train_examples.append(InputExample(texts=[q.text, kb_map[rel_id]]))

        if not train_examples:
            raise ValueError("No valid training pairs found for fine-tuning")

        train_device = "mps" if torch.backends.mps.is_available() else "cpu"
        logger.info(
            "Fine-tuning %s with %d pairs on device: %s",
            self.name,
            len(train_examples),
            train_device,
        )

        try:
            self.model.to(train_device)
            dataloader = DataLoader(
                train_examples,
                shuffle=True,
                batch_size=min(batch_size, len(train_examples)),
            )
            loss_fn = losses.MultipleNegativesRankingLoss(self.model)

            self.model.fit(
                train_objectives=[(dataloader, loss_fn)],
                epochs=epochs,
                warmup_steps=0,
                show_progress_bar=False,
            )
        finally:
            # Crucial: always return to CPU for evaluation & benchmarks
            if self.model is not None:
                self.model.to("cpu")
            self.device = "cpu"

        # Re-index with updated weights
        self.index(kb)

    def save(self, path: str | Path) -> None:
        """Save fine-tuned model weights to directory."""
        target_dir = Path(path)
        target_dir.mkdir(parents=True, exist_ok=True)
        if self.model is None:
            raise RuntimeError("Cannot save uninitialized SentenceTransformer model")
        self.model.save(str(target_dir))

    def load(self, path: str | Path) -> None:
        """Load model weights from directory."""
        target_dir = Path(path)
        if not target_dir.exists() or not target_dir.is_dir():
            raise FileNotFoundError(f"Weights directory not found: {target_dir}")
        expected_files = ["modules.json", "config.json", "model.safetensors"]
        if not any((target_dir / fname).exists() for fname in expected_files):
            raise FileNotFoundError(
                f"Weights directory {target_dir} is missing model artifacts "
                f"(expected one of {expected_files})"
            )
        self.model_id = str(target_dir)
        self._load_model()
