"""Tool schemas offered to the LLM, derived from contracts TOOL_CATALOG."""

from typing import Any

from contracts import TOOL_CATALOG
from contracts.envelope import VerificationState
from contracts.tools import ALL_STATES, CODE_FLOOR, VERIFICATION_PATH

# What follows each tool, in the names the model is offered. Behavior, not
# policy: banking-core still authorizes every call (ADR-0002, ADR-0016).
FOLLOW_UP: dict[str, str] = {
    "customer.match": (
        "It needs the document number the customer wrote in this conversation (a "
        "[DOC_n] placeholder); if they have not given one, do not call it: ask for "
        "their document type and number first. When it matches and the customer's "
        "request needs a verified session, call otp_send next, in the same turn."
    ),
    "otp.send": "Then ask the customer for the code and pass it to otp_verify.",
    "otp.verify": "Once VERIFIED, continue with what the customer asked for.",
    "card.list": (
        "Use the card_ref it returns for card_block. If the customer has more than "
        "one card and has not said which, ask before blocking."
    ),
    "transaction.list_recent": (
        "Use it to show the customer their recent charges and identify together "
        "the one they do not recognize; pass its transaction_id to card_block and "
        "to handoff_create."
    ),
    "handoff.create": (
        "For a person: when the customer asks, when a result requires it, or when "
        "the flow cannot go on (a refused code, a locked session). For a dispute or "
        "a charge the customer does not recognize, identify the customer first "
        "(customer_match). If the person writing is not the cardholder, or asks "
        "for a person, use CUSTOMER_REQUEST without identifying them."
    ),
}


def llm_tool_name(tool: str) -> str:
    """Function-calling names only allow [A-Za-z0-9_-]: `card.block` -> `card_block`."""
    return tool.replace(".", "_")


def _state_order(state: VerificationState) -> int:
    return list(VerificationState).index(state)


def llm_description(name: str) -> str:
    """The catalog description plus what the tool needs and what follows.

    The precondition is generated from the code floor (CODE_FLOOR), the widest a
    tool can ever run: configuration can only narrow it, so the text cannot
    promise what banking-core forbids. The path to VERIFIED comes from the
    contract's VERIFICATION_PATH, the edges banking-core's flow hint follows.
    """
    parts = [TOOL_CATALOG[name].description.rstrip()]
    states = CODE_FLOOR[name]
    if states != ALL_STATES:
        names = " or ".join(s.value for s in sorted(states, key=_state_order))
        parts.append(f"Runs only when the session is {names}.")
        if states == {VerificationState.VERIFIED}:
            path = ", then ".join(llm_tool_name(t) for _, t in VERIFICATION_PATH)
            parts.append(f"A session becomes VERIFIED through {path}.")
    if name in FOLLOW_UP:
        parts.append(FOLLOW_UP[name])
    return " ".join(parts)


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
                    "description": llm_description(name),
                    "parameters": definition.input_model.model_json_schema(),
                },
            }
        )
    return tools, names
