"""The embedding harness: questions without a gold snippet, the searched field and the
score-floor section. A fake cosine adapter stands in for a model."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml
from calibrate import runner
from calibrate.runner import load_queries_dataset, run_embedding_calibration
from retrieval.models import KBSnippet

KB = [
    {
        "id": "block.01.es",
        "topic_id": "block.01",
        "lang": "es",
        "title": "Bloqueo",
        "text": "bloqueo",
    },
    {
        "id": "block.01.pt",
        "topic_id": "block.01",
        "lang": "pt",
        "title": "Bloqueio",
        "text": "bloqueio",
    },
    {
        "id": "fees.01.es",
        "topic_id": "fees.01",
        "lang": "es",
        "title": "Comisiones",
        "text": "comisiones",
    },
    {
        "id": "fees.01.pt",
        "topic_id": "fees.01",
        "lang": "pt",
        "title": "Tarifas",
        "text": "tarifas",
    },
]
QUERIES = [
    {
        "id": "q1",
        "text": "congelar tarjeta",
        "kb_query": "cobro de comisión",
        "lang": "es",
        "relevant_ids": ["block.01.es"],
        "split": "test",
    },
    {
        "id": "q2",
        "text": "me cobraron comisión",
        "kb_query": "cobro de comisión",
        "lang": "es",
        "relevant_ids": ["fees.01.es"],
        "split": "test",
    },
    {
        "id": "q3",
        "text": "receta de pizza",
        "kb_query": "receta de pizza",
        "lang": "es",
        "relevant_ids": [],
        "split": "test",
    },
]


class FakeCosine:
    """Cosine-like scores: 0.9 for the topic a keyword names, 0.85 for the other
    topic when the query mentions a card, 0.5 otherwise."""

    name = "fake"

    def __init__(self, cand: dict) -> None:
        self.ids: list[str] = []

    def index(self, kb: Sequence[KBSnippet]) -> None:
        self.ids = [s.id for s in kb]

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        def score(doc: str) -> float:
            if "tarjeta" in query and doc.startswith("block"):
                return 0.9
            if "comisi" in query and doc.startswith("fees"):
                return 0.9
            return 0.5

        return sorted(((d, score(d)) for d in self.ids), key=lambda x: -x[1])[:top_k]


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(runner.RETRIEVAL_ADAPTER_REGISTRY, "fake_cosine", FakeCosine)
    kb_path, queries_path = tmp_path / "kb.jsonl", tmp_path / "queries.jsonl"
    kb_path.write_text("".join(json.dumps(r) + "\n" for r in KB))
    queries_path.write_text("".join(json.dumps(r) + "\n" for r in QUERIES))

    def write(**extra: object) -> Path:
        cfg = {
            "task": "embedding",
            "kb_path": str(kb_path),
            "queries_path": str(queries_path),
            "eval_split": "test",
            "k_list": [1],
            "languages": ["es"],
            "candidates": [
                {"name": "fake", "type": "fake_cosine", "model_id": "fake-cosine"},
                {"name": "bm25", "type": "bm25", "model_id": "bm25"},
            ],
            **extra,
        }
        path = tmp_path / "embedding.yaml"
        path.write_text(yaml.safe_dump(cfg))
        return path

    return write


def _row(report: str, model: str) -> list[str]:
    line = next(
        x for x in report.splitlines() if x.startswith(f"| `{model}` | zeroshot | es |")
    )
    return [c.strip() for c in line.strip("|").split("|")]


def test_questions_without_gold_leave_hit_at_k(config, tmp_path: Path) -> None:
    report = run_embedding_calibration(config(), tmp_path / "out").read_text()
    # Two answerable questions, both right: the off-topic one is not a miss.
    assert _row(report, "fake-cosine")[3] == "1.000"
    assert "Score Floor" not in report


def test_the_searched_field_comes_from_the_config(config, tmp_path: Path) -> None:
    report = run_embedding_calibration(
        config(query_field="kb_query"), tmp_path / "out"
    ).read_text()
    # q1's kb_query points at the wrong topic, so only q2 is right.
    assert _row(report, "fake-cosine")[3] == "0.500"
    assert "**Searched field:** `kb_query`" in report


def test_the_floor_section_counts_lost_and_wrongly_answered(
    config, tmp_path: Path
) -> None:
    report = run_embedding_calibration(
        config(score_floor=0.8), tmp_path / "out"
    ).read_text()
    assert "## Score Floor (0.80)" in report
    assert "| `fake-cosine` | es | 2 | 0.000 | 1 | 0.000 |" in report
    assert "| `bm25` | es |" not in report.split("## Score Floor")[1]

    lenient = run_embedding_calibration(
        config(score_floor=0.4), tmp_path / "out2"
    ).read_text()
    assert "| `fake-cosine` | es | 2 | 0.000 | 1 | 1.000 |" in lenient


def test_a_floor_outside_zero_to_one_is_refused(config, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="score_floor"):
        run_embedding_calibration(config(score_floor=1.5), tmp_path / "out")


def test_a_missing_searched_field_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    path.write_text(
        json.dumps({"id": "q9", "text": "hola", "lang": "es", "split": "test"}) + "\n"
    )
    with pytest.raises(ValueError, match="'q9' has no 'kb_query'"):
        load_queries_dataset(path, query_field="kb_query")
