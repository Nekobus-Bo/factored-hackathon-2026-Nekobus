"""banking-core's flow hint (ADR-0016) as the model reads it."""

from orchestrator.conversation.engine import _name_flow_tools


def test_flow_tools_are_renamed_to_the_offered_function_names():
    payload = {
        "tool": "card.list",
        "status": "refused",
        "reason_code": "STATE_NOT_ALLOWED",
        "data": None,
        "flow": {
            "state": "IDENTIFIED",
            "next": ["otp.send"],
            "allowed": ["customer.match", "otp.send", "handoff.create"],
            "required_states": ["VERIFIED"],
        },
    }
    _name_flow_tools(payload)
    assert payload["flow"] == {
        "state": "IDENTIFIED",
        "next": ["otp_send"],
        "allowed": ["customer_match", "otp_send", "handoff_create"],
        "required_states": ["VERIFIED"],
    }


def test_a_result_without_a_hint_reads_as_before():
    payload = {"tool": "kb.search", "status": "ok", "data": {}, "flow": None}
    _name_flow_tools(payload)
    assert "flow" not in payload


def test_empty_required_states_are_dropped():
    payload = {
        "flow": {
            "state": "VERIFIED",
            "next": [],
            "allowed": [],
            "required_states": None,
        }
    }
    _name_flow_tools(payload)
    assert payload["flow"] == {"state": "VERIFIED", "next": [], "allowed": []}


def test_enabled_tools_shape_what_the_model_is_offered():
    from orchestrator.conversation.engine import TurnEngine

    engine = TurnEngine.__new__(TurnEngine)
    from orchestrator.conversation.tools import build_llm_tools

    engine.tools, engine._tool_names = build_llm_tools()
    assert engine._offered(None) == engine.tools
    offered = engine._offered(["customer.match", "otp.send", "handoff.create"])
    assert [t["function"]["name"] for t in offered] == [
        "customer_match",
        "handoff_create",
        "otp_send",
    ]


def test_descriptions_state_the_code_floor_and_the_next_step():
    from orchestrator.conversation.tools import llm_description

    block = llm_description("card.block")
    assert "Runs only when the session is VERIFIED." in block
    assert "customer_match, then otp_send, then otp_verify" in block
    match = llm_description("customer.match")
    assert "Runs only when the session is ANONYMOUS or IDENTIFIED." in match
    assert "otp_send next" in match
    assert "Runs only" not in llm_description("kb.search")
