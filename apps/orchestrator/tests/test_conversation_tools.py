"""Tool schemas offered to the LLM come from contracts TOOL_CATALOG."""

from contracts import TOOL_CATALOG
from orchestrator.conversation.tools import build_llm_tools
from orchestrator.llm.replay import compute_tool_schema_hash


def test_every_catalog_tool_is_offered_with_its_input_schema():
    tools, names = build_llm_tools()

    assert sorted(names.values()) == sorted(TOOL_CATALOG)
    for tool in tools:
        fn = tool["function"]
        definition = TOOL_CATALOG[names[fn["name"]]]
        assert fn["parameters"] == definition.input_model.model_json_schema()
        assert "." not in fn["name"]


def test_tool_schema_hash_is_stable():
    first, _ = build_llm_tools()
    second, _ = build_llm_tools()
    assert compute_tool_schema_hash(first) == compute_tool_schema_hash(second)
