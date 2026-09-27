import tempfile

import pytest
from encoder.adapters import GLiNERAdapter, TFIDFLRAdapter
from retrieval.adapters import BM25Adapter, SentenceTransformersAdapter


def test_gliner_adapter_invalid_model_id_raises():
    """GLiNERAdapter must raise RuntimeError on invalid model ID, never swallow."""
    with pytest.raises(RuntimeError, match="Could not load GLiNER model"):
        GLiNERAdapter(model_id="nonexistent-org/nonexistent-model-xyz-123")


def test_gliner_adapter_load_nonexistent_dir_raises():
    """GLiNERAdapter.load() must raise FileNotFoundError for non-existent path."""
    with pytest.raises(FileNotFoundError, match="Weights directory not found"):
        adapter = GLiNERAdapter.__new__(GLiNERAdapter)
        adapter.load("/nonexistent/weights/directory")


def test_gliner_adapter_load_corrupted_dir_raises():
    """GLiNERAdapter.load() must raise FileNotFoundError if weights missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = GLiNERAdapter.__new__(GLiNERAdapter)
        with pytest.raises(FileNotFoundError, match="missing model artifacts"):
            adapter.load(tmpdir)


def test_sentence_transformers_adapter_invalid_model_id_raises():
    """SentenceTransformersAdapter must raise RuntimeError on invalid model ID."""
    with pytest.raises(RuntimeError, match="Could not load SentenceTransformer"):
        SentenceTransformersAdapter(
            model_id="nonexistent-org/nonexistent-model-xyz-123"
        )


def test_sentence_transformers_adapter_load_nonexistent_dir_raises():
    """SentenceTransformersAdapter.load() raises FileNotFoundError on missing dir."""
    adapter = SentenceTransformersAdapter.__new__(SentenceTransformersAdapter)
    with pytest.raises(FileNotFoundError, match="Weights directory not found"):
        adapter.load("/nonexistent/weights/dir")


def test_sentence_transformers_adapter_load_corrupted_dir_raises():
    """SentenceTransformersAdapter.load() raises FileNotFoundError on missing files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = SentenceTransformersAdapter.__new__(SentenceTransformersAdapter)
        with pytest.raises(FileNotFoundError, match="missing model artifacts"):
            adapter.load(tmpdir)


def test_tfidf_lr_adapter_predict_unfitted_raises():
    """TFIDFLRAdapter must raise RuntimeError when predicting before fit()."""
    adapter = TFIDFLRAdapter()
    with pytest.raises(RuntimeError, match="must be fitted before predict"):
        adapter.predict(["test query"], candidate_intents=["card_block"])


def test_tfidf_lr_adapter_load_nonexistent_raises():
    """TFIDFLRAdapter.load() must raise FileNotFoundError for non-existent file."""
    adapter = TFIDFLRAdapter()
    with pytest.raises(FileNotFoundError):
        adapter.load("/nonexistent/model.joblib")


def test_bm25_adapter_search_unindexed_returns_empty():
    """BM25Adapter returns empty search results if unindexed."""
    adapter = BM25Adapter()
    assert adapter.search("test") == []


def test_bm25_adapter_load_nonexistent_raises():
    """BM25Adapter.load() must raise FileNotFoundError for non-existent file."""
    adapter = BM25Adapter()
    with pytest.raises(FileNotFoundError):
        adapter.load("/nonexistent/bm25.json")


def test_gliner_adapter_predict_missing_intent_or_confidence_raises():
    """GLiNERAdapter must raise if gliner2 output lacks intent or confidence."""
    adapter = GLiNERAdapter.__new__(GLiNERAdapter)
    adapter._is_gliner2 = True

    class StubSchema:
        def classification(self, name, labels):
            pass

        def entities(self, labels):
            pass

    class StubModelMissingIntent:
        def create_schema(self):
            return StubSchema()

        def extract(self, text, schema, **kwargs):
            return {}

    adapter.model = StubModelMissingIntent()
    with pytest.raises(RuntimeError, match="lacks 'intent' field"):
        adapter.predict(["test text"], candidate_intents=["card_block"])

    class StubModelMissingConfidence:
        def create_schema(self):
            return StubSchema()

        def extract(self, text, schema, **kwargs):
            return {"intent": {"label": "card_block"}}

    adapter.model = StubModelMissingConfidence()
    with pytest.raises(RuntimeError, match="lacks 'intent.confidence'"):
        adapter.predict(["test text"], candidate_intents=["card_block"])

    class StubModelMissingLabel:
        def create_schema(self):
            return StubSchema()

        def extract(self, text, schema, **kwargs):
            return {"intent": {"confidence": 0.95}}

    adapter.model = StubModelMissingLabel()
    with pytest.raises(RuntimeError, match="lacks 'intent.label'"):
        adapter.predict(["test text"], candidate_intents=["card_block"])
