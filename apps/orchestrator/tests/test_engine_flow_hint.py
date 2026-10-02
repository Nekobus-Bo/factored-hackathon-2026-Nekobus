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
