"""The detective-mode turn trace (ADR-0019): one detail per event, named after its kind."""

import pytest
from pydantic import ValidationError

from contracts.trace import (
    BlocksDetail,
    MaskingDetail,
    ToolCallDetail,
    TraceEvent,
    TraceEventKind,
    TraceEventStatus,
    TurnTrace,
)

NO_DETAIL = {
    "note": None,
    "encoder": None,
    "masking": None,
    "decisions": None,
    "llm_call": None,
    "tool_call": None,
    "blocks": None,
}


def _event(kind: TraceEventKind, **details: object) -> TraceEvent:
    return TraceEvent(
        seq=0,
        kind=kind,
        label=kind.value,
        start_ms=0.0,
        duration_ms=1.5,
        status=TraceEventStatus.OK,
        **{**NO_DETAIL, **details},
    )


MASKING = MaskingDetail(
    masked_text="soy [DOCUMENT_1]",
    placeholders=["[DOCUMENT_1]"],
    regex_only=False,
    encoder_spans_added=0,
    otp_pending=False,
    failed=False,
)
TOOL = ToolCallDetail(
    call_id="call_1",
    llm_name="card_block",
    tool="card.block",
    arguments='{"card_id": "[CARD_1]"}',
    executed=True,
    local_reason=None,
    status="ok",
    reason_code=None,
    flow_state="VERIFIED",
    flow_next=["handoff.create"],
    flow_allowed=["card.block"],
    feedback='{"status": "ok"}',
)


def test_an_event_carries_the_detail_named_after_its_kind() -> None:
    assert _event(TraceEventKind.MASKING, masking=MASKING).masking == MASKING


def test_an_engine_handoff_carries_a_tool_call_detail() -> None:
    assert _event(TraceEventKind.ENGINE_HANDOFF, tool_call=TOOL).tool_call == TOOL


@pytest.mark.parametrize("kind", [TraceEventKind.CANNED_REPLY, TraceEventKind.TAKEOVER])
def test_a_note_only_event_carries_no_detail(kind: TraceEventKind) -> None:
    assert _event(kind, note="answered without the LLM").note == "answered without the LLM"
    with pytest.raises(ValidationError):
        _event(kind, masking=MASKING)


def test_a_missing_or_foreign_detail_is_refused() -> None:
    with pytest.raises(ValidationError):
        _event(TraceEventKind.MASKING)
    with pytest.raises(ValidationError):
        _event(TraceEventKind.TOOL_CALL, masking=MASKING)
    with pytest.raises(ValidationError):
        _event(TraceEventKind.TOOL_CALL, tool_call=TOOL, masking=MASKING)


def test_a_trace_round_trips_through_json() -> None:
    blocks = BlocksDetail(
        kept=["text"], dropped=[], internal_lines_withheld=0, receipts=1, handoffs=0, fallback=False
    )
    trace = TurnTrace(
        trace_version="1",
        turn_id="turn_1",
        prompt_version="p1",
        total_ms=12.5,
        tool_rounds=1,
        events=[
            _event(TraceEventKind.MASKING, masking=MASKING),
            _event(TraceEventKind.TOOL_CALL, tool_call=TOOL),
            _event(TraceEventKind.BLOCKS, blocks=blocks),
        ],
    )
    assert TurnTrace.model_validate_json(trace.model_dump_json()) == trace


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        TraceEvent.model_validate({**_event(TraceEventKind.TAKEOVER).model_dump(), "raw": "x"})
