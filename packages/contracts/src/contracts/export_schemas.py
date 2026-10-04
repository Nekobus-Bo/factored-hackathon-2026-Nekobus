"""Deterministic JSON Schema export for Pattern Blue tool contracts."""

import argparse
import json
from pathlib import Path
from typing import Any

from contracts.blocks import MESSAGE_BLOCK_ADAPTER
from contracts.encoder import (
    AnalyzeRequest,
    AnalyzeResponse,
    DecisionPointsResponse,
    EmbedRequest,
    EmbedResponse,
)
from contracts.envelope import Receipt, ToolCall, ToolResult
from contracts.tools import TOOL_CATALOG
from contracts.trace import TurnTrace


def _to_deterministic_json(data: dict[str, Any]) -> str:
    """Serializes a dictionary to deterministic, pretty-printed JSON."""
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def export_schemas(output_dir: Path | str | None = None) -> dict[str, Path]:
    """Exports deterministic JSON schemas for all tool contracts and envelopes.

    Returns a mapping of logical schema names to their written file paths.
    """
    if output_dir is None:
        target_dir = Path(__file__).resolve().parent.parent.parent / "schemas"
    else:
        target_dir = Path(output_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    exported_files: dict[str, Path] = {}

    # 1. Export envelopes
    envelopes_dir = target_dir / "envelope"
    envelopes_dir.mkdir(parents=True, exist_ok=True)

    envelope_models = {
        "tool_call": ToolCall,
        "tool_result": ToolResult,
        "receipt": Receipt,
    }

    for name, model_cls in sorted(envelope_models.items()):
        schema = model_cls.model_json_schema()
        out_file = envelopes_dir / f"{name}.json"
        out_file.write_text(_to_deterministic_json(schema), encoding="utf-8")
        exported_files[f"envelope/{name}"] = out_file

    # 2. Export tools
    tools_dir = target_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    catalog_data: dict[str, Any] = {
        "version": "1.0",
        "tools": {},
    }

    for tool_name, definition in sorted(TOOL_CATALOG.items()):
        normalized_name = tool_name.replace(".", "_")

        input_schema = definition.input_model.model_json_schema()
        output_schema = definition.output_model.model_json_schema()

        input_file = tools_dir / f"{normalized_name}.input.json"
        output_file = tools_dir / f"{normalized_name}.output.json"

        input_file.write_text(_to_deterministic_json(input_schema), encoding="utf-8")
        output_file.write_text(_to_deterministic_json(output_schema), encoding="utf-8")

        exported_files[f"tools/{normalized_name}.input"] = input_file
        exported_files[f"tools/{normalized_name}.output"] = output_file

        catalog_data["tools"][tool_name] = {
            "name": definition.name,
            "description": definition.description,
            "is_write": definition.is_write,
            "mutates_state": definition.mutates_state,
            "requires_idempotency": definition.requires_idempotency,
            "permitted_states": sorted([s.value for s in definition.permitted_states]),
            "input_schema_file": f"tools/{normalized_name}.input.json",
            "output_schema_file": f"tools/{normalized_name}.output.json",
        }

    # 3. Export encoder schemas
    encoder_dir = target_dir / "encoder"
    encoder_dir.mkdir(parents=True, exist_ok=True)

    encoder_models = {
        "analyze_request": AnalyzeRequest,
        "analyze_response": AnalyzeResponse,
        "decision_points_response": DecisionPointsResponse,
        "embed_request": EmbedRequest,
        "embed_response": EmbedResponse,
    }

    for name, model_cls in sorted(encoder_models.items()):
        schema = model_cls.model_json_schema()
        out_file = encoder_dir / f"{name}.json"
        out_file.write_text(_to_deterministic_json(schema), encoding="utf-8")
        exported_files[f"encoder/{name}"] = out_file

    # 4. Export message blocks
    blocks_dir = target_dir / "blocks"
    blocks_dir.mkdir(parents=True, exist_ok=True)
    block_file = blocks_dir / "message_block.json"
    block_file.write_text(
        _to_deterministic_json(MESSAGE_BLOCK_ADAPTER.json_schema()), encoding="utf-8"
    )
    exported_files["blocks/message_block"] = block_file

    # 5. Export the detective-mode turn trace (ADR-0019)
    trace_dir = target_dir / "trace"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_file = trace_dir / "turn_trace.json"
    trace_file.write_text(_to_deterministic_json(TurnTrace.model_json_schema()), encoding="utf-8")
    exported_files["trace/turn_trace"] = trace_file

    # 6. Export catalog manifest
    catalog_file = target_dir / "catalog.json"
    catalog_file.write_text(_to_deterministic_json(catalog_data), encoding="utf-8")
    exported_files["catalog"] = catalog_file

    return exported_files


def main() -> None:
    """CLI entrypoint for schema generation."""
    parser = argparse.ArgumentParser(
        description="Export deterministic JSON Schemas for Pattern Blue contracts",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Output directory path (defaults to packages/contracts/schemas)",
    )
    args = parser.parse_args()

    files = export_schemas(output_dir=args.out_dir)
    print(f"Exported {len(files)} deterministic schema files successfully.")


if __name__ == "__main__":
    main()
