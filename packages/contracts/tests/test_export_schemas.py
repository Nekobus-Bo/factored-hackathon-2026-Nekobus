"""Tests verifying deterministic JSON Schema export and committed schema drift guard."""

import json
from pathlib import Path

from contracts.export_schemas import export_schemas
from contracts.tools import TOOL_CATALOG


def test_export_schemas_is_byte_identical_across_runs(tmp_path: Path):
    """Schema export must be 100% deterministic and byte-identical across multiple runs."""
    run1_dir = tmp_path / "run1"
    run2_dir = tmp_path / "run2"

    files1 = export_schemas(output_dir=run1_dir)
    files2 = export_schemas(output_dir=run2_dir)

    assert set(files1.keys()) == set(files2.keys())
    assert len(files1) > 0

    all_relative_paths1 = sorted([p.relative_to(run1_dir) for p in run1_dir.rglob("*.json")])
    all_relative_paths2 = sorted([p.relative_to(run2_dir) for p in run2_dir.rglob("*.json")])

    assert all_relative_paths1 == all_relative_paths2

    for rel_path in all_relative_paths1:
        content1 = (run1_dir / rel_path).read_bytes()
        content2 = (run2_dir / rel_path).read_bytes()
        assert content1 == content2, f"Schema mismatch in {rel_path}"

        # Verify it parses as valid JSON
        data = json.loads(content1.decode("utf-8"))
        assert isinstance(data, dict)


def test_exported_catalog_completeness(tmp_path: Path):
    """Catalog manifest contains all 10 tools with permitted states and mutates_state flags."""
    run_dir = tmp_path / "schemas"
    export_schemas(output_dir=run_dir)

    catalog_path = run_dir / "catalog.json"
    assert catalog_path.exists()

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog["version"] == "1.0"
    assert len(catalog["tools"]) == 10

    for tool_name, definition in TOOL_CATALOG.items():
        assert tool_name in catalog["tools"]
        tool_entry = catalog["tools"][tool_name]
        assert tool_entry["name"] == definition.name
        assert tool_entry["mutates_state"] == definition.mutates_state
        assert tool_entry["requires_idempotency"] == definition.requires_idempotency
        expected_states = sorted([s.value for s in definition.permitted_states])
        assert tool_entry["permitted_states"] == expected_states


def test_handoff_output_schema_exposes_server_built_fields(tmp_path: Path) -> None:
    export_schemas(output_dir=tmp_path)
    schema = json.loads(
        (tmp_path / "tools" / "handoff_create.output.json").read_text(encoding="utf-8")
    )

    assert {"priority", "summary"} <= set(schema["properties"])
    assert {"priority", "summary"} <= set(schema["required"])


def test_committed_schemas_match_fresh_export(tmp_path: Path):
    """Drift guard: asserts committed schemas match a fresh export byte-for-byte."""
    committed_dir = Path(__file__).resolve().parent.parent / "schemas"
    fresh_dir = tmp_path / "fresh_schemas"

    assert committed_dir.exists(), "Committed schemas directory must exist"

    export_schemas(output_dir=fresh_dir)

    committed_files = sorted([p.relative_to(committed_dir) for p in committed_dir.rglob("*.json")])
    fresh_files = sorted([p.relative_to(fresh_dir) for p in fresh_dir.rglob("*.json")])

    assert committed_files == fresh_files, "Committed schemas list differs from fresh export"

    for rel_path in committed_files:
        committed_bytes = (committed_dir / rel_path).read_bytes()
        fresh_bytes = (fresh_dir / rel_path).read_bytes()
        assert committed_bytes == fresh_bytes, (
            f"Drift detected in committed schema: {rel_path}. Re-export schemas to sync."
        )
