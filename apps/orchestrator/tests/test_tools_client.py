"""Unit tests for typed BankingCoreClient (ADR-0001, ADR-0004).

Verifies:
- Session creation via POST /v1/sessions
- Tool calls via POST /v1/tools/call with X-Session-Id header
- Request and response validation with contracts ToolCall and ToolResult models
- Timeout and HTTP error mapping to ToolResult status=error
  with closed reason code (no free text)
"""

from datetime import UTC, datetime

import httpx
import pytest
import respx
from contracts.envelope import (
    ReasonCode,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from orchestrator.config import Settings
from orchestrator.tools_client import (
    BankingCoreClient,
    BankingCoreSyncClient,
    SessionCreationError,
)


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        banking_core_url="http://banking-core.test:8081",
        banking_core_timeout_seconds=2.0,
    )


@pytest.mark.asyncio
@respx.mock
async def test_create_session_success(test_settings: Settings) -> None:
    respx.post("http://banking-core.test:8081/v1/sessions").mock(
        return_value=httpx.Response(201, json={"session_id": "sess_opaque_12345"})
    )

    async with BankingCoreClient(settings=test_settings) as client:
        session_id = await client.create_session()
        assert session_id == "sess_opaque_12345"


@pytest.mark.asyncio
@respx.mock
async def test_create_session_failure(test_settings: Settings) -> None:
    respx.post("http://banking-core.test:8081/v1/sessions").mock(
        return_value=httpx.Response(500, json={"error": "server down"})
    )

    async with BankingCoreClient(settings=test_settings) as client:
        with pytest.raises(SessionCreationError):
            await client.create_session()


@pytest.mark.asyncio
@respx.mock
async def test_call_tool_success_with_receipt(test_settings: Settings) -> None:
    receipt_data = {
        "action": "card.block",
        "target_masked": "card_test_9999",
        "state_before": "ACTIVE",
        "state_after": "BLOCKED",
        "verified_at": datetime.now(UTC).isoformat(),
        "audit_id": "audit_ref_12345678",
    }
    mock_result_data = {
        "tool": "card.block",
        "status": "ok",
        "data": {
            "card_ref": "card_test_9999",
            "status": "BLOCKED",
            "receipt": receipt_data,
        },
    }

    call_route = respx.post("http://banking-core.test:8081/v1/tools/call").mock(
        return_value=httpx.Response(200, json=mock_result_data)
    )

    tool_call = ToolCall(
        tool="card.block",
        args={"card_ref": "card_test_9999", "reason": "LOST"},
        idempotency_key="idem_key_card_block_01",
    )

    async with BankingCoreClient(settings=test_settings) as client:
        result = await client.call_tool(
            session_id="sess_xyz",
            tool_call=tool_call,
        )

        assert call_route.called
        last_req = call_route.calls.last.request
        assert last_req.headers["x-session-id"] == "sess_xyz"

        assert isinstance(result, ToolResult)
        assert result.status == ToolResultStatus.OK
        assert result.tool == "card.block"
        assert result.data is not None
        assert result.data["status"] == "BLOCKED"


@pytest.mark.asyncio
@respx.mock
async def test_call_tool_refused_by_policy(test_settings: Settings) -> None:
    mock_refusal = {
        "tool": "card.block",
        "status": "refused",
        "reason_code": "STATE_NOT_ALLOWED",
        "data": None,
    }

    respx.post("http://banking-core.test:8081/v1/tools/call").mock(
        return_value=httpx.Response(200, json=mock_refusal)
    )

    tool_call = ToolCall(
        tool="card.block",
        args={"card_ref": "card_test_9999", "reason": "LOST"},
        idempotency_key="idem_key_card_block_02",
    )

    async with BankingCoreClient(settings=test_settings) as client:
        result = await client.call_tool(
            session_id="sess_xyz",
            tool_call=tool_call,
        )

        assert result.status == ToolResultStatus.REFUSED
        assert result.reason_code == ReasonCode.STATE_NOT_ALLOWED
        assert result.data is None


@pytest.mark.asyncio
@respx.mock
async def test_call_tool_timeout_maps_to_internal_error(
    test_settings: Settings,
) -> None:
    respx.post("http://banking-core.test:8081/v1/tools/call").mock(
        side_effect=httpx.TimeoutException("Connection timed out")
    )

    tool_call = ToolCall(
        tool="card.block",
        args={"card_ref": "card_test_9999", "reason": "LOST"},
        idempotency_key="idem_key_card_block_03",
    )

    async with BankingCoreClient(settings=test_settings) as client:
        result = await client.call_tool(
            session_id="sess_xyz",
            tool_call=tool_call,
        )

        # Mapped to status=error with closed reason code INTERNAL_ERROR and NO free text
        assert result.status == ToolResultStatus.ERROR
        assert result.reason_code == ReasonCode.INTERNAL_ERROR
        assert result.data is None


@pytest.mark.asyncio
@respx.mock
async def test_call_tool_502_bad_gateway_maps_to_internal_error(
    test_settings: Settings,
) -> None:
    respx.post("http://banking-core.test:8081/v1/tools/call").mock(
        return_value=httpx.Response(502, text="<html>502 Bad Gateway</html>")
    )

    tool_call = ToolCall(
        tool="card.block",
        args={"card_ref": "card_test_9999", "reason": "LOST"},
        idempotency_key="idem_key_card_block_04",
    )

    async with BankingCoreClient(settings=test_settings) as client:
        result = await client.call_tool(
            session_id="sess_xyz",
            tool_call=tool_call,
        )

        assert result.status == ToolResultStatus.ERROR
        assert result.reason_code == ReasonCode.INTERNAL_ERROR
        assert result.data is None


@respx.mock
def test_sync_client_success_and_timeout(test_settings: Settings) -> None:
    respx.post("http://banking-core.test:8081/v1/sessions").mock(
        return_value=httpx.Response(200, json={"session_id": "sync_sess_123"})
    )
    respx.post("http://banking-core.test:8081/v1/tools/call").mock(
        side_effect=httpx.TimeoutException("Read timeout")
    )

    with BankingCoreSyncClient(settings=test_settings) as client:
        sess = client.create_session()
        assert sess == "sync_sess_123"

        tool_call = ToolCall(
            tool="card.block",
            args={"card_ref": "card_test_9999", "reason": "LOST"},
            idempotency_key="idem_key_card_block_05",
        )
        res = client.call_tool(sess, tool_call)
        assert res.status == ToolResultStatus.ERROR
        assert res.reason_code == ReasonCode.INTERNAL_ERROR
        assert res.data is None
