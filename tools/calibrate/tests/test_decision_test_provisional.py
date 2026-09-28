"""Integrity of the provisional held-out decision test set.

data/eval/synthetic/decision.test.provisional.jsonl is written free-form (not by
tools/synthdata) and stands in for the human set until it exists.
"""

import json
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml
from encoder.models import DecisionExample

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNTH_DIR = REPO_ROOT / "data" / "eval" / "synthetic"
TEST_PATH = SYNTH_DIR / "decision.test.provisional.jsonl"
TRAINING_PATHS = [
    SYNTH_DIR / "decision.train.jsonl",
    SYNTH_DIR / "decision.validation.jsonl",
]
SEED_FIXTURES = REPO_ROOT / "apps/banking-core/src/banking_core/seed/fixtures.py"
PII_SLOTS = {
    "document_number",
    "full_name",
    "birth_date",
    "email",
    "phone",
    "card_number",
    "otp_code",
}
DOCUMENT_TYPES = {"NATIONAL_ID", "PASSPORT", "FOREIGN_ID", "TAX_ID"}
PER_INTENT_PER_LANG = 10


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return _load(TEST_PATH)


@pytest.fixture(scope="module")
def training_rows() -> list[dict]:
    return [r for p in TRAINING_PATHS for r in _load(p)]


@pytest.fixture(scope="module")
def schema() -> dict:
    return yaml.safe_load((SYNTH_DIR / "schema.yaml").read_text("utf-8"))


def test_rows_validate_as_decision_examples(rows):
    assert len(rows) == 450
    for row in rows:
        example = DecisionExample(**row)
        assert example.split == "test"
        assert example.source == "synthetic-provisional"
    assert len({r["id"] for r in rows}) == len(rows)


def test_labels_match_schema(rows, schema):
    intents = {i["name"] for i in schema["intents"]}
    slot_types = {s["name"] for s in schema["slots"]}
    for row in rows:
        assert row["lang"] in schema["languages"], row["id"]
        assert row["intent"] in intents, row["id"]
        for slot in row["slots"]:
            assert slot["type"] in slot_types, row["id"]
            if slot["type"] == "document_type":
                assert slot["normalized"] in DOCUMENT_TYPES, row["id"]
            else:
                assert "normalized" not in slot, row["id"]


def test_offsets_are_exact(rows):
    for row in rows:
        text = row["text"]
        for slot in row["slots"]:
            assert 0 <= slot["start"] < slot["end"] <= len(text), row["id"]
            assert text[slot["start"] : slot["end"]] == slot["value"], row["id"]
            assert slot["value"] == slot["value"].strip(), row["id"]


def test_counts_per_intent_per_language(rows, schema):
    counts = Counter((r["lang"], r["intent"]) for r in rows)
    expected = {
        (lang, intent["name"]): PER_INTENT_PER_LANG
        for lang in schema["languages"]
        for intent in schema["intents"]
    }
    assert counts == expected


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def test_no_text_overlap_with_train_or_validation(rows, training_rows):
    seen = {_norm(r["text"]) for r in training_rows}
    overlap = [r["id"] for r in rows if _norm(r["text"]) in seen]
    assert not overlap, f"test texts also in train/validation: {overlap}"


def test_pii_disjoint_from_train_and_validation(rows, training_rows):
    train_pii = {
        _norm(s["value"])
        for r in training_rows
        for s in r["slots"]
        if s["type"] in PII_SLOTS
    }
    shared = {
        s["value"]
        for r in rows
        for s in r["slots"]
        if s["type"] in PII_SLOTS and _norm(s["value"]) in train_pii
    }
    assert not shared, f"test PII also used in train/validation: {shared}"


def test_pii_disjoint_from_seed_and_scenarios(rows):
    sources = [SEED_FIXTURES, *sorted((REPO_ROOT / "eval/scenarios").rglob("*"))]
    corpus = _norm("\n".join(p.read_text("utf-8") for p in sources if p.is_file()))
    documents = re.findall(
        r'_DOCUMENT_[A-Z]{2} = "([^"]+)"', SEED_FIXTURES.read_text("utf-8")
    )
    assert documents, "seed fixture document constants not found"

    leaked = set()
    for row in rows:
        for doc in documents:
            if doc in row["text"]:
                leaked.add(doc)
        for slot in row["slots"]:
            if slot["type"] in PII_SLOTS and _norm(slot["value"]) in corpus:
                leaked.add(slot["value"])
    assert not leaked, f"test set reuses seed/scenario identities: {leaked}"
