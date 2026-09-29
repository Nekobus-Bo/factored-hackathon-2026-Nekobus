"""Turn engine over the real LLMProvider: record once, then replay offline.

litellm is patched, so no API key is involved. Asserts that raw PII is absent
both from what litellm receives and from the replay recordings on disk.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from contracts import ReceiptBlock
from orchestrator.config import Settings
from orchestrator.conversation import ConversationContext, TurnEngine
from orchestrator.llm.provider import LLMProvider
from orchestrator.tools_client import BankingCoreClient

from .fake_llm import tool_call
from .test_conversation_engine import (
    BANKING_URL,
    OK_DATA,
    RAW_DOCUMENT,
    SESSION_ID,
    FakeBankingCore,
    receipt,
)

USER_TEXT = f"Perdí mi tarjeta, mi cédula es {RAW_DOCUMENT}"


def litellm_response(
    content: str | None = None, tool_calls: list[dict[str, Any]] | None = None
) -> MagicMock:
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls or []
    response.choices = [choice]
    response.usage.model_dump.return_value = {"total_tokens": 10}
    return response


SCRIPT = [
    litellm_response(
        tool_calls=[
            tool_call(
                "call_1",
                "customer_match",
                {"document_type": "NATIONAL_ID", "document_number": "[DOC_1]"},
            )
        ]
    ),
    litellm_response(tool_calls=[tool_call("call_2", "otp_send", {})]),
    litellm_response(content="Te envié un código de verificación."),
]


def engine_for(settings: Settings) -> TurnEngine:
    return TurnEngine(
        llm=LLMProvider(settings=settings),
        banking=BankingCoreClient(base_url=BANKING_URL, settings=settings),
    )


@pytest.fixture
def banking() -> Any:
    fake = FakeBankingCore()
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=fake)
        yield fake


async def test_record_then_replay_without_network(
    tmp_path: Path, banking: FakeBankingCore
) -> None:
    # 1. Record: live mode with a patched litellm
    record_settings = Settings(
        llm_mode="live", llm_model="test-model", replay_dir=str(tmp_path), record=True
    )
    with (
        patch("litellm.acompletion", new_callable=AsyncMock) as acompletion,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        acompletion.side_effect = SCRIPT
        recorded = await engine_for(record_settings).run_turn(
            ConversationContext(session_id=SESSION_ID), USER_TEXT, turn_id="t1"
        )

    sent = json.dumps([c.kwargs["messages"] for c in acompletion.call_args_list])
    assert acompletion.call_count == 3
    assert RAW_DOCUMENT not in sent
    assert "[DOC_1]" in sent
    recordings = list(tmp_path.glob("*.json"))
    assert len(recordings) == 3
    for path in recordings:
        assert RAW_DOCUMENT not in path.read_text(encoding="utf-8")
    assert banking.calls_to("customer.match")[0]["args"]["document_number"] == (
        RAW_DOCUMENT
    )

    # 2. Replay: same turn, no network allowed
    replay_settings = Settings(
        llm_mode="replay", llm_model="test-model", replay_dir=str(tmp_path)
    )
    with patch("litellm.acompletion", new_callable=AsyncMock) as acompletion:
        acompletion.side_effect = AssertionError("network call in replay mode")
        replayed = await engine_for(replay_settings).run_turn(
            ConversationContext(session_id=SESSION_ID), USER_TEXT, turn_id="t1"
        )

    assert acompletion.call_count == 0
    assert replayed.blocks == recorded.blocks
    assert replayed.metadata.llm_recording_keys == recorded.metadata.llm_recording_keys


async def test_replay_does_not_depend_on_the_ids_and_times_of_a_run(
    tmp_path: Path,
) -> None:
    """A recording made on one run replays on another with different receipts."""
    later_run = {
        "otp.send": {
            **OK_DATA["otp.send"],
            "challenge_id": "chal_zzzzzzzz",
            "receipt": {
                **receipt("otp.send", "chal_zzzzzzzz", "NONE", "ISSUED"),
                "verified_at": "2026-10-04T09:15:30.250000Z",
                "audit_id": "aud_00004321",
            },
        }
    }
    with respx.mock(assert_all_called=False) as router:
        route = router.post(f"{BANKING_URL}/v1/tools/call")

        route.mock(side_effect=FakeBankingCore())
        record_settings = Settings(
            llm_mode="live",
            llm_model="test-model",
            replay_dir=str(tmp_path),
            record=True,
        )
        with (
            patch("litellm.acompletion", new_callable=AsyncMock) as acompletion,
            patch("litellm.completion_cost", return_value=0.0),
        ):
            acompletion.side_effect = SCRIPT
            recorded = await engine_for(record_settings).run_turn(
                ConversationContext(session_id=SESSION_ID), USER_TEXT, turn_id="t1"
            )

        route.mock(side_effect=FakeBankingCore(data=later_run))
        replay_settings = Settings(
            llm_mode="replay", llm_model="test-model", replay_dir=str(tmp_path)
        )
        with patch("litellm.acompletion", new_callable=AsyncMock) as acompletion:
            acompletion.side_effect = AssertionError("network call in replay mode")
            replayed = await engine_for(replay_settings).run_turn(
                ConversationContext(session_id=SESSION_ID), USER_TEXT, turn_id="t1"
            )

    assert len(recorded.metadata.llm_recording_keys) == 3
    assert replayed.metadata.llm_recording_keys == recorded.metadata.llm_recording_keys
    # The customer still sees the receipt of the run they are in.
    receipts = [b.receipt for b in replayed.blocks if isinstance(b, ReceiptBlock)]
    assert {r.audit_id for r in receipts} == {"aud_00004321"}
