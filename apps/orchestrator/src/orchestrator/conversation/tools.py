"""Tool schemas offered to the LLM, derived from contracts TOOL_CATALOG."""

from typing import Any

from contracts import TOOL_CATALOG


def llm_tool_name(tool: str) -> str:
    """Function-calling names only allow [A-Za-z0-9_-]: `card.block` -> `card_block`."""
    return tool.replace(".", "_")


def build_llm_tools() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return (OpenAI-style tool schemas, llm name -> catalog name).

    Sorted by name so the schema hash that feeds the replay key is stable.
    """
    tools: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for name, definition in sorted(TOOL_CATALOG.items()):
        llm_name = llm_tool_name(name)
        if llm_name in names:
            raise ValueError(f"Tool name collision after normalization: {llm_name}")
        names[llm_name] = name
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": llm_name,
                    "description": definition.description,
                    "parameters": definition.input_model.model_json_schema(),
                },
            }
        )
    return tools, names
