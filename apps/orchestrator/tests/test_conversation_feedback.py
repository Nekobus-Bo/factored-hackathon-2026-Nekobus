"""What the model is shown of a tool result, and why it must be run-stable.

The replay key hashes the masked message history. A field that differs on every
run (audit id, timestamp, random ref) would give every LLM call after a write a
new key, so a recorded session could never replay.
"""

import json
from typing import Any

import httpx
import pytest
import respx
from contracts import TOOL_CATALOG, HandoffBlock, ReceiptBlock, ToolResult
from orchestrator.conversation.engine import LLM_HIDDEN_FIELDS
from orchestrator.llm.replay import compute_recording_key, compute_tool_schema_hash
from pydantic import BaseModel

from .fake_llm import ScriptedLLM, Step, tool_call
from .test_conversation_engine import (
    ANALYZE_OK,
    BANKING_URL,
    ENCODER_URL,
    OK_DATA,
    FakeBankingCore,
    make_engine,
    new_context,
    receipt,
)

RUN_VARYING = (
    "audit_id",
    "verified_at",
    "challenge_id",
    "handoff_id",
    "queue_position",
    "created_at",
    "target_masked",
    "summary",
)


def run_data(tag: str, audit: int, when: str) -> dict[str, dict[str, Any]]:
    """OK_DATA as one particular run would produce it: ids, audit ids, times."""

    def stamped(action: str, target: str, before: str, after: str) -> dict[str, Any]:
        return {
            **receipt(action, target, before, after),
            "verified_at": when,
            "audit_id": f"aud_{audit:08d}",
        }

    handoff = OK_DATA["handoff.create"]
    return {
        "otp.send": {
            **OK_DATA["otp.send"],
            "challenge_id": f"chal_{tag}",
            "receipt": stamped("otp.send", f"chal_{tag}", "NONE", "ISSUED"),
        },
        "card.block": {
            **OK_DATA["card.block"],
            "receipt": stamped("card.block", "card_ab12cd34", "ACTIVE", "BLOCKED"),
        },
        "handoff.create": {
            **handoff,
            "handoff_id": f"hnd_{tag}",
            "queue_position": audit % 9 + 1,
            "created_at": when,
            "summary": {
                **handoff["summary"],
                "actions_taken": [
                    {
                        "action": "card.block",
                        "decision": "allowed",
                        "reason_code": None,
                        "audit_id": f"aud_{audit:08d}",
                    }
                ],
            },
            "receipt": stamped("handoff.create", f"hnd_{tag}", "NONE", "QUEUED"),
        },
    }


def scripted_writes() -> ScriptedLLM:
    return ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_a", "otp_send", {})]),
            Step(
                tool_calls=[
                    tool_call(
                        "call_b",
                        "card_block",
                        {"card_ref": "card_ab12cd34", "reason": "LOST"},
                    )
                ]
            ),
            Step(
                tool_calls=[
                    tool_call(
                        "call_c",
                        "handoff_create",
                        {
                            "reason": "DISPUTE_CLAIM",
                            "summary": "Customer reported a lost card.",
                        },
                    )
                ]
            ),
            Step(content="Listo: bloqueé tu tarjeta y abrí un caso."),
        ]
    )


@pytest.fixture
def mock_services() -> Any:
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{ENCODER_URL}/v1/analyze").mock(
            return_value=httpx.Response(200, json=ANALYZE_OK)
        )
        yield router


async def test_runs_with_different_receipts_show_the_model_the_same_history(
    mock_services: Any,
) -> None:
    banking_route = mock_services.post(f"{BANKING_URL}/v1/tools/call")
    runs = []
    for tag, audit, when in (
        ("aaaaaaaa", 7, "2026-09-27T12:00:00Z"),
        ("zzzzzzzz", 4321, "2026-10-02T08:30:15.123456Z"),
    ):
        banking_route.mock(side_effect=FakeBankingCore(data=run_data(tag, audit, when)))
        llm = scripted_writes()
        result = await make_engine(llm).run_turn(
            new_context(), "Perdí mi tarjeta", turn_id="t1"
        )
        runs.append((llm, result))
    (llm_a, result_a), (llm_b, result_b) = runs

    # Same LLM-visible history => same replay key for every call of the turn.
    assert llm_a.calls == llm_b.calls
    assert len(llm_a.calls) == 4

    def keys(llm: ScriptedLLM) -> list[str]:
        return [
            compute_recording_key(
                "model", "v1", c["messages"], compute_tool_schema_hash(c["tools"])
            )
            for c in llm.calls
        ]

    assert keys(llm_a) == keys(llm_b)
    assert len(set(keys(llm_a))) == 4
    # Tool results as the model sees them (its own call arguments and the tool
    # schemas legitimately mention "summary").
    seen = "\n".join(
        m["content"] for c in llm_a.calls for m in c["messages"] if m["role"] == "tool"
    )
    for name in RUN_VARYING:
        assert name not in seen
    for value in ("aaaaaaaa", "aud_00000007", "2026-09-27T12:00:00Z"):
        assert value not in seen
    # What the model needs to act is still there.
    assert "card_ab12cd34" in seen
    assert '"state_after": "BLOCKED"' in seen
    assert "simulated" in seen

    # The customer-facing blocks are built from the full result: nothing lost.
    assert result_a.blocks != result_b.blocks
    for tag, audit, result in (("aaaaaaaa", 7, result_a), ("zzzzzzzz", 4321, result_b)):
        receipts = [b.receipt for b in result.blocks if isinstance(b, ReceiptBlock)]
        assert [r.action for r in receipts] == ["otp.send", "card.block"]
        assert {r.audit_id for r in receipts} == {f"aud_{audit:08d}"}
        assert receipts[0].target_masked == f"chal_{tag}"
        [handoff] = [b for b in result.blocks if isinstance(b, HandoffBlock)]
        assert handoff.handoff_id == f"hnd_{tag}"
        assert handoff.receipt.audit_id == f"aud_{audit:08d}"
        assert handoff.queue_position == audit % 9 + 1


def feedback_data(tool: str) -> dict[str, Any]:
    result = ToolResult.model_validate(
        {"tool": tool, "status": "ok", "data": OK_DATA[tool]}
    )
    engine = make_engine(ScriptedLLM([]))
    feedback = json.loads(engine._tool_feedback(tool.replace(".", "_"), result, {}))
    assert feedback["tool"] == tool
    assert feedback["status"] == "ok"
    data: dict[str, Any] = feedback["data"]
    return data


@pytest.mark.parametrize(
    ("tool", "kept"),
    [
        ("otp.send", {"sent", "channel", "destination_masked", "expires_in_seconds"}),
        ("otp.verify", {"verified", "state", "attempts_remaining"}),
        ("card.block", {"card_ref", "status"}),
        ("handoff.create", {"status", "department", "priority"}),
    ],
)
def test_writes_keep_only_what_the_model_acts_on(tool: str, kept: set[str]) -> None:
    data = feedback_data(tool)

    assert set(data) == kept | {"receipt"}
    assert set(data["receipt"]) == {"action", "state_before", "state_after"}
    assert data["receipt"]["action"] == tool


@pytest.mark.parametrize("tool", ["customer.match", "card.list", "kb.search"])
def test_reads_are_shown_whole(tool: str) -> None:
    assert feedback_data(tool) == json.loads(json.dumps(OK_DATA[tool]))


def test_otp_verify_outcome_stays_readable_for_the_pending_challenge_check() -> None:
    data = feedback_data("otp.verify")

    assert data["state"] == "VERIFIED"
    assert data["verified"] is True
    assert data["attempts_remaining"] == 2


def test_every_write_tool_hides_its_run_varying_receipt_fields() -> None:
    for tool, definition in TOOL_CATALOG.items():
        if definition.mutates_state:
            hidden = LLM_HIDDEN_FIELDS.get(tool, ())
            for path in (
                "receipt.target_masked",
                "receipt.verified_at",
                "receipt.audit_id",
            ):
                assert path in hidden, f"{tool} shows {path} to the model"


def test_hidden_fields_are_real_output_fields() -> None:
    """A renamed contract field must not leave a stale entry that hides nothing."""
    for tool, paths in LLM_HIDDEN_FIELDS.items():
        for path in paths:
            model: Any = TOOL_CATALOG[tool].output_model
            *parents, leaf = path.split(".")
            for name in parents:
                model = model.model_fields[name].annotation
                assert isinstance(model, type) and issubclass(model, BaseModel)
            assert leaf in model.model_fields, f"{tool}: {path}"
