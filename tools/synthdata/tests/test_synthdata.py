"""Unit tests for synthetic dataset generator and schema.

Verifies:
1. Offsets match text[start:end] == value for every slot
2. Every intent x language is present in both splits (40 train, 10 validation)
3. No text appears in both train and validation
4. Rerun is byte-identical
5. No 'test' split allowed (ADR-0010 enforcement)
6. All 13 slots and 15 intents match schema.yaml
7. Realistic fake constraints (RFC 2606 email domains, no +00 phone prefix)
"""

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:
    yaml = None

from tools.synthdata.generate import (
    DEFAULT_SEED,
    generate_datasets,
    generate_split,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "data" / "eval" / "synthetic" / "schema.yaml"
TRAIN_PATH = REPO_ROOT / "data" / "eval" / "synthetic" / "decision.train.jsonl"
VAL_PATH = REPO_ROOT / "data" / "eval" / "synthetic" / "decision.validation.jsonl"


@pytest.fixture(scope="module")
def ensure_datasets_exist():
    """Ensure train and validation datasets are generated before running tests."""
    out_dir = REPO_ROOT / "data" / "eval" / "synthetic"
    generate_datasets(out_dir, seed=DEFAULT_SEED)
    return out_dir


@pytest.fixture(scope="module")
def train_records(ensure_datasets_exist):
    with open(TRAIN_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.fixture(scope="module")
def val_records(ensure_datasets_exist):
    with open(VAL_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_schema_yaml_structure():
    """Verify data/eval/synthetic/schema.yaml meets all specifications."""
    if yaml is None:
        pytest.skip("pyyaml is not installed in the active environment")
    assert SCHEMA_PATH.is_file(), f"schema.yaml missing at {SCHEMA_PATH}"
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    assert "version" in schema
    assert set(schema["languages"]) == {"es", "pt", "en"}
    assert len(schema["intents"]) == 15
    assert len(schema["slots"]) == 13

    # Check intent structure
    intent_names = {item["name"] for item in schema["intents"]}
    expected_intents = {
        "report_unrecognized_charge",
        "report_lost_card",
        "report_stolen_card",
        "report_suspicious_activity",
        "request_card_block",
        "request_dispute",
        "request_human_agent",
        "provide_identity_data",
        "provide_otp_code",
        "confirm",
        "deny",
        "check_balance",
        "check_recent_transactions",
        "greeting",
        "out_of_scope",
    }
    assert intent_names == expected_intents
    for item in schema["intents"]:
        assert "description" in item and len(item["description"]) > 10

    # Check slot structure
    slot_names = {item["name"] for item in schema["slots"]}
    expected_slots = {
        "document_type",
        "document_number",
        "full_name",
        "birth_date",
        "email",
        "phone",
        "card_last4",
        "card_number",
        "amount",
        "currency",
        "merchant",
        "transaction_date",
        "otp_code",
    }
    assert slot_names == expected_slots
    for item in schema["slots"]:
        assert "pii" in item and isinstance(item["pii"], bool)
        assert "pattern" in item
        assert "notes" in item


def test_slot_offsets_match(train_records, val_records):
    """Offsets match text[start:end] == value for every slot in both splits."""
    all_records = train_records + val_records
    assert len(all_records) == 2250

    total_slots_checked = 0
    for record in all_records:
        text = record["text"]
        for slot in record["slots"]:
            total_slots_checked += 1
            start = slot["start"]
            end = slot["end"]
            expected_val = slot["value"]
            actual_val = text[start:end]
            assert actual_val == expected_val, (
                f"Mismatch in record {record['id']} for slot {slot['type']}: "
                f"text[{start}:{end}]='{actual_val}' != expected '{expected_val}'"
            )

    assert total_slots_checked > 2000, "Too few slots checked across dataset"


def test_every_intent_language_present(train_records, val_records):
    """Every intent x lang pair is present (40 in train, 10 in val)."""
    train_counts = Counter((r["lang"], r["intent"]) for r in train_records)
    val_counts = Counter((r["lang"], r["intent"]) for r in val_records)

    assert len(train_counts) == 45  # 15 intents x 3 languages
    assert len(val_counts) == 45

    for key, count in train_counts.items():
        assert count == 40, f"Train count for {key} is {count}, expected 40"

    for key, count in val_counts.items():
        assert count == 10, f"Validation count for {key} is {count}, expected 10"


def test_no_train_val_text_overlap(train_records, val_records):
    """No text appears in both train and validation splits."""
    train_texts = {r["text"] for r in train_records}
    val_texts = {r["text"] for r in val_records}

    assert len(train_texts) == 1800, "Train texts contain internal duplicates"
    assert len(val_texts) == 450, "Validation texts contain internal duplicates"

    overlap = train_texts.intersection(val_texts)
    assert len(overlap) == 0, (
        f"Found {len(overlap)} overlapping texts between splits: {overlap}"
    )


def test_all_13_slots_represented(train_records, val_records):
    """All 13 slots defined in the schema are present in the generated data."""
    slots_found = {s["type"] for r in (train_records + val_records) for s in r["slots"]}
    expected_slots = {
        "document_type",
        "document_number",
        "full_name",
        "birth_date",
        "email",
        "phone",
        "card_last4",
        "card_number",
        "amount",
        "currency",
        "merchant",
        "transaction_date",
        "otp_code",
    }
    assert slots_found == expected_slots


def test_document_type_surface_and_normalized(train_records, val_records):
    """document_type slots use surface forms and have normalized enum."""
    allowed_enums = {"NATIONAL_ID", "PASSPORT", "FOREIGN_ID", "TAX_ID"}
    forbidden_in_text = {"NATIONAL_ID", "FOREIGN_ID", "TAX_ID", "PASSPORT"}

    doc_type_count = 0
    for record in train_records + val_records:
        for forbidden in forbidden_in_text:
            assert forbidden not in record["text"], (
                f"Literal enum '{forbidden}' found in text: {record['text']}"
            )
        for slot in record["slots"]:
            if slot["type"] == "document_type":
                doc_type_count += 1
                assert "normalized" in slot, (
                    f"Missing 'normalized' field in slot: {slot}"
                )
                assert slot["normalized"] in allowed_enums, (
                    f"Invalid normalized document_type '{slot['normalized']}', "
                    f"expected one of {allowed_enums}"
                )
                assert slot["value"] not in allowed_enums, (
                    f"document_type surface form '{slot['value']}' "
                    "must not be literal enum string"
                )

    assert doc_type_count > 0, "No document_type slots found in dataset"


def test_document_number_no_artificial_prefixes(train_records, val_records):
    """document_number slots must not have artificial prefixes (CC-, CPF-, etc.)."""
    forbidden_prefixes = (
        "CC-",
        "CPF-",
        "TAX-",
        "PAS-",
        "DNI-",
        "ID-",
        "NIF-",
        "RG-",
        "NIE-",
        "NIT-",
        "RNE-",
        "CRNM-",
        "SSN-",
    )
    doc_number_count = 0
    for record in train_records + val_records:
        for slot in record["slots"]:
            if slot["type"] == "document_number":
                doc_number_count += 1
                for prefix in forbidden_prefixes:
                    assert not slot["value"].startswith(prefix), (
                        f"Artificial prefix '{prefix}' found in "
                        f"document_number: '{slot['value']}'"
                    )

    assert doc_number_count > 0, "No document_number slots found in dataset"


def test_document_number_matches_type_format(train_records, val_records):
    """Every document_number matches its type format; consistent pairs."""
    from tools.synthdata.fillers import DOCUMENT_PROFILES

    checked_pairs = 0
    for record in train_records + val_records:
        slots = {s["type"]: s for s in record["slots"]}
        if "document_type" in slots and "document_number" in slots:
            checked_pairs += 1
            doc_type_val = slots["document_type"]["value"]
            doc_num_val = slots["document_number"]["value"]
            lang = record["lang"]
            matching = [
                p
                for p in DOCUMENT_PROFILES[lang]
                if p["surface"] == doc_type_val and p["number"] == doc_num_val
            ]
            assert matching, (
                f"Inconsistent pair in {record['id']} ({lang}): "
                f"type='{doc_type_val}', number='{doc_num_val}'"
            )

    assert checked_pairs > 0, "No document_type + document_number pairs found"


def test_report_suspicious_activity_no_concrete_charges(train_records, val_records):
    """report_suspicious_activity must focus on security anomalies without charges."""
    for record in train_records + val_records:
        if record["intent"] == "report_suspicious_activity":
            slot_types = {s["type"] for s in record["slots"]}
            assert "amount" not in slot_types, (
                f"Suspicious activity record '{record['id']}' "
                f"must not contain amount slot: {record['text']}"
            )


def test_amount_pattern_and_thousands_separators(train_records, val_records):
    """amount slots conform to schema pattern and include thousands separators."""
    import re

    pattern = re.compile(r"^(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)$")
    amounts = [
        s["value"]
        for r in (train_records + val_records)
        for s in r["slots"]
        if s["type"] == "amount"
    ]
    assert len(amounts) > 0

    has_thousands_separator = False
    for amt in amounts:
        assert pattern.match(amt), f"Amount '{amt}' does not match schema pattern"
        if "," in amt[:-3] or "." in amt[:-3]:
            has_thousands_separator = True

    assert has_thousands_separator, (
        "Dataset should include amounts formatted with thousands separators"
    )


def test_prohibit_test_split():
    """Generator must NEVER generate a 'test' split (enforced per ADR-0010)."""
    with pytest.raises(
        ValueError, match="Test split must never be generated synthetically"
    ):
        generate_split("test")

    with open(TRAIN_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            assert d["split"] == "train"

    with open(VAL_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            assert d["split"] == "validation"


def test_byte_identical_rerun(tmp_path):
    """Rerunning generator with the same seed produces byte-identical files."""
    dir1 = tmp_path / "run1"
    dir2 = tmp_path / "run2"

    t1, v1 = generate_datasets(dir1, seed=123)
    t2, v2 = generate_datasets(dir2, seed=123)

    assert (
        hashlib.sha256(t1.read_bytes()).hexdigest()
        == hashlib.sha256(t2.read_bytes()).hexdigest()
    )
    assert (
        hashlib.sha256(v1.read_bytes()).hexdigest()
        == hashlib.sha256(v2.read_bytes()).hexdigest()
    )


def test_fake_filler_constraints(train_records, val_records):
    """Slot values adhere to fake PII constraints: RFC 2606 domains, no +00."""
    for record in train_records + val_records:
        for slot in record["slots"]:
            val = slot["value"]
            if slot["type"] == "email":
                assert any(
                    val.endswith(d)
                    for d in ("example.com", "example.org", "example.net")
                ), f"Email '{val}' does not use RFC 2606 reserved domain"
            elif slot["type"] == "phone":
                assert not val.startswith("+00"), (
                    f"Phone '{val}' illegally starts with +00"
                )


def test_no_demo_identities_in_texts(train_records, val_records):
    """No scenario or seed identity appears in any synthetic text."""
    from tools.synthdata.denylist import find_denylisted

    leaks = {
        r["id"]: find_denylisted(r["text"])
        for r in train_records + val_records
        if find_denylisted(r["text"])
    }
    assert not leaks, f"Demo identities leaked into synthetic data: {leaks}"


def test_denylist_covers_seed_fixtures():
    """Every document constant and demo name in the seed fixtures is denylisted."""
    import re

    from tools.synthdata.denylist import DEMO_IDENTITY_DENYLIST

    fixtures = (
        REPO_ROOT / "apps/banking-core/src/banking_core/seed/fixtures.py"
    ).read_text(encoding="utf-8")
    documents = re.findall(r'^[A-Z_]+_DOCUMENT_[A-Z]{2} = "([^"]+)"$', fixtures, re.M)
    assert len(documents) == 9, "seed fixture document constants changed shape"
    demo_names = {"Carlos Gomez", "Mariana Silva", "Alice Johnson"}
    fixture_names = re.findall(r'^\s+"([A-Z][a-z]+ [A-Z][a-z]+)",$', fixtures, re.M)
    assert demo_names <= set(fixture_names), "seed demo customer names changed"

    missing = (set(documents) | demo_names) - set(DEMO_IDENTITY_DENYLIST)
    assert not missing, f"Denylist is missing seed identities: {sorted(missing)}"


def test_generation_rejects_denylisted_text(tmp_path, monkeypatch):
    """The generator refuses to write a row containing a demo identity."""
    from tools.synthdata import generate as gen

    real_split = gen.generate_split

    def leaky_split(split, **kwargs):
        rows = real_split(split, **kwargs)
        rows[0] = {**rows[0], "text": rows[0]["text"] + " 1020304050", "slots": []}
        return rows

    monkeypatch.setattr(gen, "generate_split", leaky_split)
    with pytest.raises(ValueError, match="demo identities"):
        gen.generate_datasets(tmp_path, seed=DEFAULT_SEED)
