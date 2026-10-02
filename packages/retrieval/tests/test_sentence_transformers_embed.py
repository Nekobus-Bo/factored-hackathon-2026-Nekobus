"""SentenceTransformersAdapter.embed is the one function behind index, search and the
model server's /v1/embed. Tested against a stand-in for the library, which the
`vector` extra installs and CI does not need."""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Generator
from typing import Any

import numpy as np
import pytest
from retrieval import KBSnippet


class FakeSentenceTransformer:
    """Returns rows that are NOT unit length unless asked to normalize."""

    calls: list[dict[str, Any]] = []
    loaded: list[dict[str, Any]] = []

    def __init__(self, model_id: str, device: str = "cpu", **kwargs: Any) -> None:
        self.model_id = model_id
        FakeSentenceTransformer.loaded.append({"model_id": model_id, **kwargs})

    def get_embedding_dimension(self) -> int:
        return 3

    def to(self, device: str) -> None:
        pass

    def encode(self, texts: Any, **kwargs: Any) -> np.ndarray:
        FakeSentenceTransformer.calls.append({"texts": texts, **kwargs})
        items = [texts] if isinstance(texts, str) else list(texts)
        rows = np.array([[len(t), 1.0, 0.0] for t in items], dtype=np.float64)
        if kwargs.get("normalize_embeddings"):
            rows = rows / np.linalg.norm(rows, axis=1, keepdims=True)
        return rows[0] if isinstance(texts, str) else rows


@pytest.fixture
def adapter_module(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[types.ModuleType, None, None]:
    st = types.ModuleType("sentence_transformers")
    st.SentenceTransformer = FakeSentenceTransformer  # type: ignore[attr-defined]
    st.InputExample = object  # type: ignore[attr-defined]
    st.losses = types.SimpleNamespace()  # type: ignore[attr-defined]
    torch = types.ModuleType("torch")
    torch.backends = types.SimpleNamespace(  # type: ignore[attr-defined]
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    utils = types.ModuleType("torch.utils")
    data = types.ModuleType("torch.utils.data")
    data.DataLoader = object  # type: ignore[attr-defined]
    for name, module in (
        ("sentence_transformers", st),
        ("torch", torch),
        ("torch.utils", utils),
        ("torch.utils.data", data),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(
        sys.modules, "retrieval.adapters.sentence_transformers", raising=False
    )
    FakeSentenceTransformer.calls = []
    FakeSentenceTransformer.loaded = []
    module = importlib.import_module("retrieval.adapters.sentence_transformers")
    yield module
    sys.modules.pop("retrieval.adapters.sentence_transformers", None)
    import retrieval.adapters

    if hasattr(retrieval.adapters, "sentence_transformers"):
        delattr(retrieval.adapters, "sentence_transformers")


def test_embed_returns_unit_float32_rows(adapter_module: types.ModuleType) -> None:
    adapter = adapter_module.SentenceTransformersAdapter(model_id="local/path")
    vectors = adapter.embed(["hola", "buenos dias"])
    assert vectors.dtype == np.float32 and vectors.shape == (2, 3)
    assert np.linalg.norm(vectors, axis=1) == pytest.approx([1.0, 1.0], abs=1e-6)
    assert FakeSentenceTransformer.calls[-1]["normalize_embeddings"] is True


def test_index_and_search_use_embed(adapter_module: types.ModuleType) -> None:
    adapter = adapter_module.SentenceTransformersAdapter(model_id="local/path")
    kb = [
        KBSnippet(id="a.es", lang="es", title="uno", text="dos"),
        KBSnippet(id="b.es", lang="es", title="uno dos tres cuatro", text="cinco"),
    ]
    adapter.index(kb)
    assert adapter.corpus_embeddings is not None
    assert np.array_equal(
        adapter.corpus_embeddings, adapter.embed([f"{s.title} {s.text}" for s in kb])
    )
    ranking = adapter.search("uno dos", top_k=2)
    assert {doc for doc, _ in ranking} == {"a.es", "b.es"}
    # The query goes through the same function, as a one-element batch.
    assert FakeSentenceTransformer.calls[-1]["texts"] == ["uno dos"]


def test_an_empty_index_keeps_its_shape(adapter_module: types.ModuleType) -> None:
    adapter = adapter_module.SentenceTransformersAdapter(model_id="local/path")
    adapter.index([])
    assert adapter.corpus_embeddings is not None
    assert adapter.corpus_embeddings.shape == (0, 3)
    assert adapter.search("x") == []


def test_weights_load_in_float32_unless_configured(
    adapter_module: types.ModuleType,
) -> None:
    adapter_module.SentenceTransformersAdapter(model_id="local/path")
    adapter_module.SentenceTransformersAdapter(model_id="local/path", dtype="bfloat16")
    assert [c["model_kwargs"] for c in FakeSentenceTransformer.loaded] == [
        {"dtype": "float32"},
        {"dtype": "bfloat16"},
    ]


def test_an_unknown_dtype_fails_before_loading(
    adapter_module: types.ModuleType,
) -> None:
    with pytest.raises(ValueError, match="float32, bfloat16"):
        adapter_module.SentenceTransformersAdapter(model_id="local/path", dtype="int8")
    assert FakeSentenceTransformer.loaded == []
