"""Drift guard for typed contracts/labels.py against data/eval/synthetic/schema.yaml."""

from pathlib import Path

from contracts.generate_labels import generate_labels_code, parse_schema_yaml
from contracts.labels import Intent, PiiType, SlotType


def test_labels_drift_guard():
    """contracts/labels.py must match schema.yaml generated content byte-for-byte."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    schema_path = repo_root / "data" / "eval" / "synthetic" / "schema.yaml"
    labels_py_path = Path(__file__).resolve().parent.parent / "src" / "contracts" / "labels.py"

    assert schema_path.is_file(), f"schema.yaml missing at {schema_path}"
    assert labels_py_path.is_file(), f"labels.py missing at {labels_py_path}"

    expected_code = generate_labels_code(schema_path)
    actual_code = labels_py_path.read_text(encoding="utf-8")

    assert actual_code == expected_code, (
        f"Drift detected between {schema_path} and {labels_py_path}. "
        "Run 'make generate-labels' to re-sync."
    )


def test_labels_enum_members_match_schema():
    """Verify Intent and SlotType members correspond to schema.yaml items."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    schema_path = repo_root / "data" / "eval" / "synthetic" / "schema.yaml"

    intents, slots = parse_schema_yaml(schema_path)

    assert set(intents) == {item.value for item in Intent}
    assert len(intents) == len(Intent)

    assert set(slots) == {item.value for item in SlotType}
    assert len(slots) == len(SlotType)


def test_pii_type_enum():
    """Verify PiiType enum supports uppercase and case-insensitive resolution."""
    expected_pii = {"DOC", "NAME", "PHONE", "EMAIL", "CARD", "DATE", "OTP", "SECRET"}
    assert {p.value for p in PiiType} == expected_pii

    # Case-insensitivity check via _missing_
    assert PiiType("card") == PiiType.CARD
    assert PiiType("email") == PiiType.EMAIL
    assert PiiType("DOC") == PiiType.DOC
