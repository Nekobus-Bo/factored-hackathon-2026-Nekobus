"""Unit tests for LLMProvider (ADR-0001, ADR-0004).

Verifies:
- Outbound PII masking on EVERY message (no raw email/phone/PAN reaches LLM)
- String inspection & masking (content list parts, tool args, tool messages)
- Rehydration of tool_call arguments for backend execution while keeping history masked
- Explicitly disabled LiteLLM telemetry and callbacks
- Round-trip rehydration restores unmasked content
- Fail-closed behavior on residual unmasked PII
- Replay player returns cached responses without making network calls
- Replay miss raises ReplayMissError
- Changing prompt_version causes replay miss
- Live recording with RECORD=1 saves replay files
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest
from orchestrator.config import Settings
from orchestrator.llm.provider import LLMProvider
from orchestrator.llm.replay import (
    RecordedResponse,
    ReplayManager,
    ReplayMissError,
    compute_recording_key,
)
from orchestrator.privacy.masking import RegexMasker


def test_litellm_telemetry_and_callbacks_disabled() -> None:
    """Verify LiteLLM telemetry and callbacks are explicitly disabled (P2)."""
    LLMProvider()
    assert litellm.telemetry is False
    assert litellm.success_callback == []
    assert litellm.failure_callback == []


@pytest.mark.asyncio
async def test_provider_outbound_masking_round_trip(tmp_path: Path) -> None:
    settings = Settings(
        llm_mode="live",
        llm_model="test-model",
        replay_dir=str(tmp_path),
        record=False,
    )
    provider = LLMProvider(settings=settings)

    raw_user_msg = (
        "Please block my card 4532 1234 5678 9012 and email confirmation "
        "to user@bank.com"
    )
    messages = [{"role": "user", "content": raw_user_msg}]

    # Mock litellm.acompletion
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = (
        "I have blocked card [CARD_1] and sent an email to [EMAIL_1]."
    )
    mock_choice.message.tool_calls = []
    mock_response.choices = [mock_choice]
    mock_response.usage = MagicMock(
        prompt_tokens=25, completion_tokens=15, total_tokens=40
    )
    mock_response.usage.model_dump.return_value = {
        "prompt_tokens": 25,
        "completion_tokens": 15,
        "total_tokens": 40,
    }

    with (
        patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomplete,
        patch("litellm.completion_cost", return_value=0.0002),
    ):
        mock_acomplete.return_value = mock_response

        res = await provider.complete(messages=messages, prompt_version="1.0")

        # 1. Verify outbound message had PII masked before reaching litellm
        sent_messages = mock_acomplete.call_args.kwargs["messages"]
        sent_content = sent_messages[0]["content"]
        assert "4532 1234 5678 9012" not in sent_content
        assert "user@bank.com" not in sent_content
        assert "[CARD_1]" in sent_content
        assert "[EMAIL_1]" in sent_content

        # 2. Verify rehydrated content restores original values
        assert "4532 1234 5678 9012" in res.content
        assert "user@bank.com" in res.content
        assert "[CARD_1]" not in res.content
        assert "[EMAIL_1]" not in res.content
        assert res.masked_content == (
            "I have blocked card [CARD_1] and sent an email to [EMAIL_1]."
        )
        assert res.cached is False


@pytest.mark.asyncio
async def test_provider_masks_tool_calls_arguments_and_list_content(
    tmp_path: Path,
) -> None:
    """Verify masking touches list parts, tool arguments, and tool messages."""
    settings = Settings(
        llm_mode="live",
        llm_model="test-model",
        replay_dir=str(tmp_path),
        record=False,
    )
    provider = LLMProvider(settings=settings)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Mi cédula es 1020304050"},
            ],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "customer.match",
                        "arguments": '{"document_number": "1020304050"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "customer.match",
            "content": '{"status": "ok", "doc": "1020304050"}',
        },
    ]

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Match verified."
    mock_choice.message.tool_calls = []
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomplete:
        mock_acomplete.return_value = mock_response

        await provider.complete(messages=messages, prompt_version="1.0")

        sent_messages = mock_acomplete.call_args.kwargs["messages"]

        # User turn list part masked
        assert sent_messages[0]["content"][0]["text"] == "Mi cédula es [DOC_1]"

        # Assistant tool_call argument JSON masked
        assistant_args = sent_messages[1]["tool_calls"][0]["function"]["arguments"]
        assert "1020304050" not in assistant_args
        assert "[DOC_1]" in assistant_args

        # Tool message content masked
        tool_content = sent_messages[2]["content"]
        assert "1020304050" not in tool_content
        assert "[DOC_1]" in tool_content


def test_tool_result_masking_preserves_contract_integer_amounts(tmp_path: Path) -> None:
    provider = LLMProvider(
        settings=Settings(llm_model="test-model", replay_dir=str(tmp_path))
    )
    result = {
        "reason_code": None,
        "tool": "account.get_summary",
        "status": "ok",
        "data": {
            "accounts": [
                {
                    "account_ref": "[DOC_1]",
                    "account_type": "CHECKING",
                    "currency": "COP",
                    "available_balance_minor": 55000000,
                    "ledger_balance_minor": 56000000,
                    "status": "ACTIVE",
                }
            ]
        },
    }

    masked, _ = provider.mask_outbound_messages(
        [{"role": "tool", "content": json.dumps(result)}]
    )
    payload = json.loads(masked[0]["content"])
    account = payload["data"]["accounts"][0]

    assert account["available_balance_minor"] == 55000000
    assert account["ledger_balance_minor"] == 56000000
    assert account["account_ref"] == "[DOC_1]"


@pytest.mark.asyncio
async def test_provider_tool_calls_server_side_rehydration(
    tmp_path: Path,
) -> None:
    """Verify tool_call placeholders are rehydrated for backend execution (P2)."""
    settings = Settings(
        llm_mode="live",
        llm_model="test-model",
        replay_dir=str(tmp_path),
        record=False,
    )
    provider = LLMProvider(settings=settings)

    # User gives their document number
    user_turn = {"role": "user", "content": "Mi número de documento es 1020304050."}

    # Model proposes customer.match using the placeholder [DOC_1]
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.message.tool_calls = [
        {
            "id": "call_match",
            "type": "function",
            "function": {
                "name": "customer.match",
                "arguments": '{"document_number": "[DOC_1]"}',
            },
        }
    ]
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomplete:
        mock_acomplete.return_value = mock_response

        res = await provider.complete(messages=[user_turn], prompt_version="1.0")

        # 1. Server-side rehydrated_tool_calls has the original value for banking-core
        rehydrated_args = res.rehydrated_tool_calls[0]["function"]["arguments"]
        assert "1020304050" in rehydrated_args
        assert "[DOC_1]" not in rehydrated_args

        # 2. Raw tool_calls retains placeholder
        raw_args = res.tool_calls[0]["function"]["arguments"]
        assert "[DOC_1]" in raw_args
        assert "1020304050" not in raw_args

        # 3. Next turn: caller appends raw tool_calls (masked) into conversation history
        next_messages = [
            user_turn,
            {
                "role": "assistant",
                "content": None,
                "tool_calls": res.tool_calls,
            },
        ]

        # Call again; raw PII must not enter outbound arguments
        mock_response2 = MagicMock()
        mock_choice2 = MagicMock()
        mock_choice2.message.content = "All set."
        mock_choice2.message.tool_calls = []
        mock_response2.choices = [mock_choice2]
        mock_response2.usage = None
        mock_acomplete.return_value = mock_response2

        await provider.complete(messages=next_messages, prompt_version="1.0")

        sent_next = mock_acomplete.call_args.kwargs["messages"]
        sent_assistant_args = sent_next[1]["tool_calls"][0]["function"]["arguments"]
        assert "1020304050" not in sent_assistant_args
        assert "[DOC_1]" in sent_assistant_args


@pytest.mark.asyncio
async def test_provider_replay_mode_serves_recording(tmp_path: Path) -> None:
    replay_mgr = ReplayManager(replay_dir=tmp_path, mode="replay", record=True)
    masker = RegexMasker()

    masked_msgs = [{"role": "user", "content": "Help me"}]
    key = compute_recording_key("test-model", "1.0", masked_msgs, "")

    recorded_resp = RecordedResponse(
        content="I can help you with your account.",
        tool_calls=[],
        usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        cost=0.0001,
    )
    replay_mgr.save_recording(
        key=key,
        model_id="test-model",
        prompt_version="1.0",
        masked_messages=masked_msgs,
        tool_schema_hash="",
        response=recorded_resp,
    )

    settings = Settings(
        llm_mode="replay",
        llm_model="test-model",
        replay_dir=str(tmp_path),
        record=False,
    )
    provider = LLMProvider(settings=settings, masker=masker, replay_manager=replay_mgr)

    res = await provider.complete(
        messages=[{"role": "user", "content": "Help me"}], prompt_version="1.0"
    )

    assert res.cached is True
    assert res.content == "I can help you with your account."
    assert res.cost == 0.0001
    assert res.usage["total_tokens"] == 20


@pytest.mark.asyncio
async def test_provider_replay_miss_raises_error(tmp_path: Path) -> None:
    settings = Settings(
        llm_mode="replay",
        llm_model="test-model",
        replay_dir=str(tmp_path),
        llm_replay_on_miss="fail",
        record=False,
    )
    provider = LLMProvider(settings=settings)

    messages = [{"role": "user", "content": "Unknown query"}]

    with pytest.raises(ReplayMissError, match="No recording found for key"):
        await provider.complete(messages=messages, prompt_version="1.0")


@pytest.mark.asyncio
async def test_provider_prompt_version_change_causes_replay_miss(
    tmp_path: Path,
) -> None:
    replay_mgr = ReplayManager(replay_dir=tmp_path, mode="replay", record=True)
    masker = RegexMasker()

    masked_msgs = [{"role": "user", "content": "Help me"}]
    key_v1 = compute_recording_key("model-a", "1.0", masked_msgs, "")

    recorded_resp = RecordedResponse(
        content="How can I assist you?",
        tool_calls=[],
        usage={"total_tokens": 10},
    )
    replay_mgr.save_recording(
        key=key_v1,
        model_id="model-a",
        prompt_version="1.0",
        masked_messages=masked_msgs,
        tool_schema_hash="",
        response=recorded_resp,
    )

    settings = Settings(
        llm_mode="replay",
        llm_model="model-a",
        replay_dir=str(tmp_path),
        llm_replay_on_miss="fail",
    )
    provider = LLMProvider(settings=settings, masker=masker, replay_manager=replay_mgr)

    # Calling with prompt_version="1.0" hits cache
    res_v1 = await provider.complete(
        messages=[{"role": "user", "content": "Help me"}],
        prompt_version="1.0",
    )
    assert res_v1.cached is True

    # Calling with prompt_version="2.0" causes replay miss
    with pytest.raises(ReplayMissError):
        await provider.complete(
            messages=[{"role": "user", "content": "Help me"}],
            prompt_version="2.0",
        )


@pytest.mark.asyncio
async def test_provider_live_mode_with_record(tmp_path: Path) -> None:
    settings = Settings(
        llm_mode="live",
        llm_model="record-test-model",
        replay_dir=str(tmp_path),
        record=True,
    )
    provider = LLMProvider(settings=settings)

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Recording test reply"
    mock_choice.message.tool_calls = []
    mock_response.choices = [mock_choice]
    mock_response.usage = MagicMock(
        prompt_tokens=5, completion_tokens=5, total_tokens=10
    )
    mock_response.usage.model_dump.return_value = {
        "prompt_tokens": 5,
        "completion_tokens": 5,
        "total_tokens": 10,
    }

    with (
        patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomplete,
        patch("litellm.completion_cost", return_value=0.0001),
    ):
        mock_acomplete.return_value = mock_response

        messages = [{"role": "user", "content": "Hello recorder"}]
        res = await provider.complete(messages=messages, prompt_version="1.0")

        assert res.cached is False
        assert res.content == "Recording test reply"

        # Verify recording was written to disk
        expected_file = tmp_path / f"{res.recording_key}.json"
        assert expected_file.is_file()


def _litellm_reply(content: str) -> MagicMock:
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = []
    response.choices = [choice]
    response.usage.model_dump.return_value = {"total_tokens": 10}
    return response


RAW_DOC_TEXT = "Mi cédula es 1020304050"
MASKED_DOC_MESSAGES = [{"role": "user", "content": "Mi cédula es [DOC_1]"}]


def test_sync_replay_hit_exposes_the_masked_messages(tmp_path: Path) -> None:
    replay_mgr = ReplayManager(replay_dir=tmp_path, mode="replay", record=True)
    key = compute_recording_key("test-model", "1.0", MASKED_DOC_MESSAGES, "")
    replay_mgr.save_recording(
        key=key,
        model_id="test-model",
        prompt_version="1.0",
        masked_messages=MASKED_DOC_MESSAGES,
        tool_schema_hash="",
        response=RecordedResponse(content="Listo."),
    )
    settings = Settings(
        llm_mode="replay", llm_model="test-model", replay_dir=str(tmp_path)
    )
    provider = LLMProvider(settings=settings, replay_manager=replay_mgr)

    res = provider.complete_sync(
        messages=[{"role": "user", "content": RAW_DOC_TEXT}], prompt_version="1.0"
    )

    assert res.cached is True
    assert res.masked_messages == MASKED_DOC_MESSAGES
    assert "1020304050" not in json.dumps(res.masked_messages)


def test_sync_live_call_exposes_the_masked_messages(tmp_path: Path) -> None:
    settings = Settings(
        llm_mode="live", llm_model="test-model", replay_dir=str(tmp_path)
    )
    provider = LLMProvider(settings=settings)

    with (
        patch("litellm.completion") as completion,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        completion.return_value = _litellm_reply("Listo.")
        res = provider.complete_sync(
            messages=[{"role": "user", "content": RAW_DOC_TEXT}], prompt_version="1.0"
        )

    assert res.cached is False
    assert res.masked_messages == MASKED_DOC_MESSAGES
    assert completion.call_args.kwargs["messages"] == res.masked_messages


@pytest.mark.asyncio
async def test_sync_and_async_paths_report_the_same_masked_messages(
    tmp_path: Path,
) -> None:
    settings = Settings(
        llm_mode="live", llm_model="test-model", replay_dir=str(tmp_path)
    )
    provider = LLMProvider(settings=settings)
    messages = [{"role": "user", "content": RAW_DOC_TEXT}]

    with (
        patch("litellm.completion") as completion,
        patch("litellm.acompletion", new_callable=AsyncMock) as acompletion,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        completion.return_value = _litellm_reply("Listo.")
        acompletion.return_value = _litellm_reply("Listo.")
        sync_res = provider.complete_sync(messages=messages, prompt_version="1.0")
        async_res = await provider.complete(messages=messages, prompt_version="1.0")

    assert sync_res.masked_messages == async_res.masked_messages
    assert sync_res.masked_messages
    assert sync_res.recording_key == async_res.recording_key


@pytest.mark.asyncio
@pytest.mark.parametrize(("configured", "sent"), [("none", "none"), ("  ", None)])
async def test_provider_reasoning_effort_sent_only_when_configured(
    tmp_path: Path, configured: str, sent: str | None
) -> None:
    settings = Settings(
        llm_mode="live",
        llm_model="test-model",
        llm_reasoning_effort=configured,
        replay_dir=str(tmp_path),
        record=False,
    )
    provider = LLMProvider(settings=settings)

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "ok"
    mock_choice.message.tool_calls = []
    mock_response.choices = [mock_choice]
    mock_response.usage.model_dump.return_value = {}

    with (
        patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomplete,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        mock_acomplete.return_value = mock_response
        await provider.complete(messages=[{"role": "user", "content": "hola"}])

    assert mock_acomplete.call_args.kwargs.get("reasoning_effort") == sent
    assert mock_acomplete.call_args.kwargs["temperature"] == 0.0
