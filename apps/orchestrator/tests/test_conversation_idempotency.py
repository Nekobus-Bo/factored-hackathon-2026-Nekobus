"""Idempotency keys of writes: stable across a retried turn, not tied to the LLM.

banking-core answers a repeated key from its record, so a client retry that
re-runs the turn must ask for the same write under the same key, whatever call
ids the model happens to generate on the second completion.
"""

import json
from typing import Any

import httpx
import pytest
import respx
from contracts import ReceiptBlock
from orchestrator.conversation import ConversationContext, TurnEngine

from .fake_llm import ScriptedLLM, Step, tool_call
from .test_conversation_engine import (
    ANALYZE_OK,
    BANKING_URL,
    ENCODER_URL,
    SESSION_ID,
    FakeBankingCore,
    make_engine,
    new_context,
)

BLOCK = {"card_ref": "card_ab12cd34", "reason": "LOST"}


@pytest.fixture
def banking() -> Any:
    fake = FakeBankingCore()
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{ENCODER_URL}/v1/analyze").mock(
            return_value=httpx.Response(200, json=ANALYZE_OK)
        )
        router.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=fake)
        yield fake


def keys_of(banking: FakeBankingCore, tool: str) -> list[str]:
    return [call["idempotency_key"] for call in banking.calls_to(tool)]


def block_script(call_id: str) -> ScriptedLLM:
    return ScriptedLLM(
        [
            Step(tool_calls=[tool_call(call_id, "card_block", BLOCK)]),
            Step(content="Listo: bloqueé tu tarjeta."),
        ]
    )


async def run(
    llm: ScriptedLLM, turn_id: str | None, session_id: str = SESSION_ID
) -> ConversationContext:
    context = ConversationContext(session_id=session_id, language="es")
    await make_engine(llm).run_turn(context, "Bloquea mi tarjeta", turn_id=turn_id)
    return context


async def test_key_does_not_depend_on_the_llm_call_id(banking: FakeBankingCore) -> None:
    await run(block_script("call_first_attempt"), "req-1")
    await run(block_script("call_second_attempt"), "req-1")

    first, second = keys_of(banking, "card.block")
    assert first == second
    assert first.startswith("pb-")
    assert len(first) <= 128


async def test_key_depends_on_turn_session_and_tool(banking: FakeBankingCore) -> None:
    await run(block_script("call_1"), "req-1")
    await run(block_script("call_1"), "req-2")
    await run(block_script("call_1"), "req-1", session_id="sess_other")
    otp = ScriptedLLM(
        [Step(tool_calls=[tool_call("call_1", "otp_send", {})]), Step(content="Ok.")]
    )
    await run(otp, "req-1")

    keys = keys_of(banking, "card.block") + keys_of(banking, "otp.send")
    assert len(set(keys)) == 4


async def test_without_a_turn_id_every_run_is_a_new_request(
    banking: FakeBankingCore,
) -> None:
    await run(block_script("call_1"), None)
    await run(block_script("call_1"), None)

    first, second = keys_of(banking, "card.block")
    assert first != second


async def test_writes_of_one_tool_in_a_turn_take_distinct_stable_keys(
    banking: FakeBankingCore,
) -> None:
    def two_blocks(first_id: str, second_id: str) -> ScriptedLLM:
        return ScriptedLLM(
            [
                Step(tool_calls=[tool_call(first_id, "card_block", BLOCK)]),
                Step(
                    tool_calls=[
                        tool_call(
                            second_id,
                            "card_block",
                            {"card_ref": "card_ff99ee88", "reason": "LOST"},
                        )
                    ]
                ),
                Step(content="Bloqueé las dos."),
            ]
        )

    await run(two_blocks("call_a", "call_b"), "req-1")
    await run(two_blocks("call_x", "call_y"), "req-1")

    keys = keys_of(banking, "card.block")
    assert len(keys) == 4
    assert keys[0] != keys[1]
    assert keys[:2] == keys[2:]


async def test_two_writes_in_one_completion_take_distinct_keys(
    banking: FakeBankingCore,
) -> None:
    llm = ScriptedLLM(
        [
            Step(
                tool_calls=[
                    tool_call("call_a", "card_block", BLOCK),
                    tool_call("call_a2", "card_block", BLOCK),
                ]
            ),
            Step(content="Listo."),
        ]
    )

    await run(llm, "req-1")

    first, second = keys_of(banking, "card.block")
    assert first != second


async def test_retry_after_llm_failure_reuses_the_key_of_the_completed_write(
    banking: FakeBankingCore,
) -> None:
    context = new_context()
    engine = make_engine(
        ScriptedLLM([Step(tool_calls=[tool_call("call_lost", "card_block", BLOCK)])])
    )

    # card.block runs, then the LLM fails on the next completion (the scripted
    # LLM has no step left): the turn raises and the context is left untouched.
    with pytest.raises(AssertionError, match="ran out of steps"):
        await engine.run_turn(context, "Bloquea mi tarjeta", turn_id="req-1")
    assert context.history == []
    assert len(banking.calls_to("card.block")) == 1

    # The client retries the same request: the model answers with new call ids.
    retry = make_engine(block_script("call_after_retry"))
    result = await retry.run_turn(context, "Bloquea mi tarjeta", turn_id="req-1")

    first, second = keys_of(banking, "card.block")
    assert first == second
    receipts = [b.receipt for b in result.blocks if isinstance(b, ReceiptBlock)]
    assert [r.action for r in receipts] == ["card.block"]


class ErrorOnce(FakeBankingCore):
    """Answers the first card.block with an error, like a lost response."""

    def __init__(self) -> None:
        super().__init__()
        self.pending_errors = 1

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["tool"] == "card.block" and self.pending_errors:
            self.pending_errors -= 1
            self.requests.append({"session": None, "body": body})
            return httpx.Response(
                200,
                json={
                    "tool": "card.block",
                    "status": "error",
                    "reason_code": "INTERNAL_ERROR",
                    "data": None,
                },
            )
        return super().__call__(request)


async def test_a_call_that_was_not_acknowledged_is_retried_under_its_key() -> None:
    banking = ErrorOnce()
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{ENCODER_URL}/v1/analyze").mock(
            return_value=httpx.Response(200, json=ANALYZE_OK)
        )
        router.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
        llm = ScriptedLLM(
            [
                Step(tool_calls=[tool_call("call_1", "card_block", BLOCK)]),
                Step(tool_calls=[tool_call("call_2", "card_block", BLOCK)]),
                Step(content="Listo."),
            ]
        )
        await run(llm, "req-1")

    # The first response never confirmed the write, so the second call is the
    # same write: banking-core replays it if it went through, or runs it now.
    first, second = keys_of(banking, "card.block")
    assert first == second


def test_key_helper_is_a_pure_function_of_its_inputs() -> None:
    key = TurnEngine._idempotency_key("sess_1", "turn_1", "card.block", 0)

    assert key == TurnEngine._idempotency_key("sess_1", "turn_1", "card.block", 0)
    assert key != TurnEngine._idempotency_key("sess_1", "turn_1", "card.block", 1)
    assert key != TurnEngine._idempotency_key("sess_1", "turn_2", "card.block", 0)
    assert key != TurnEngine._idempotency_key("sess_2", "turn_1", "card.block", 0)
    assert key != TurnEngine._idempotency_key("sess_1", "turn_1", "otp.send", 0)
