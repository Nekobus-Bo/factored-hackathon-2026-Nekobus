"""Typed HTTP client for calling banking-core tools through contracts."""

import logging
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx
from contracts.envelope import ReasonCode, ToolCall, ToolResult, ToolResultStatus
from pydantic import BaseModel, Field, ValidationError

from orchestrator.config import Settings, get_settings

logger = logging.getLogger(__name__)


class BankingCoreError(Exception):
    """Base exception for banking-core client communications."""


class SessionCreationError(BankingCoreError):
    """Raised when creating a session with banking-core fails."""


class InboxUnavailableError(BankingCoreError):
    """Raised when the simulated inbox cannot be read from banking-core."""


class InboxMessage(BaseModel):
    """One simulated OTP delivery for the customer's browser (ADR-0007).

    The clear code is the point of the simulation: it travels from banking-core to
    the browser through the route and nowhere else. It is kept out of the repr so
    a log line or a traceback of the object cannot carry it.
    """

    channel: str
    destination_masked: str
    code: str = Field(repr=False)
    received_at: datetime
    expires_at: datetime


class _BankingInboxMessage(BaseModel):
    """banking-core's shape for one message (created_at is when it was delivered)."""

    channel: str
    destination_masked: str
    code: str = Field(repr=False)
    created_at: datetime
    expires_at: datetime


class _BankingInbox(BaseModel):
    messages: list[_BankingInboxMessage]


class BankingCoreClient:
    """Async client communicating with banking-core through the typed contract.

    Enforces ADR-0001, ADR-0004, and AGENTS rule 1:
    - Never touches database
    - Calls banking-core over HTTP wire contract:
      POST /v1/sessions -> {session_id: str}
      GET  /v1/sessions/{session_id}/simulated-inbox -> the session's OTP messages
      POST /v1/tools/call with X-Session-Id header -> ToolResult
    - Validates request (ToolCall) and response (ToolResult)
    - Maps timeouts and network/HTTP errors to ToolResult status=error
      with closed reason code.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self.base_url = (base_url or cfg.banking_core_url).rstrip("/")
        self.timeout = (
            timeout if timeout is not None else cfg.banking_core_timeout_seconds
        )
        self._external_client = client
        self._client: httpx.AsyncClient | None = client

    async def __aenter__(self) -> "BankingCoreClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client and self._external_client is None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client if owned."""
        if self._client and self._external_client is None:
            await self._client.aclose()
            self._client = None

    async def create_session(self) -> str:
        """Issue POST /v1/sessions to obtain an opaque session_id from banking-core."""
        client = self._get_client()
        url = f"{self.base_url}/v1/sessions"
        try:
            response = await client.post(url)
            response.raise_for_status()
            data = response.json()
            session_id = data.get("session_id")
            if not session_id or not isinstance(session_id, str):
                raise SessionCreationError(
                    f"Invalid session response from banking-core: {data}"
                )
            return session_id
        except Exception as exc:
            logger.error("Failed to create banking-core session: %s", exc)
            raise SessionCreationError(f"Session creation failed: {exc}") from exc

    async def simulated_inbox(self, session_id: str) -> list[InboxMessage]:
        """Unexpired simulated OTP messages of this banking session, newest first.

        banking-core answers 404 when the session is gone or delivery is not
        simulated: there is nothing to show, which is an empty inbox, not an error.
        Anything else that is not a valid answer raises InboxUnavailableError.
        The response body holds a live code, so it is never logged or put in an
        exception message.
        """
        client = self._get_client()
        url = (
            f"{self.base_url}/v1/sessions/{quote(session_id, safe='')}/simulated-inbox"
        )
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.error("Simulated inbox request failed (%s)", type(exc).__name__)
            raise InboxUnavailableError("banking-core is unreachable") from exc
        if response.status_code == httpx.codes.NOT_FOUND:
            return []
        if response.status_code != httpx.codes.OK:
            logger.error(
                "Simulated inbox request refused: HTTP %s", response.status_code
            )
            raise InboxUnavailableError("banking-core did not serve the inbox")
        try:
            inbox = _BankingInbox.model_validate_json(response.content)
        except ValidationError:
            # Not chained: the error carries the input, and the input holds a code.
            logger.error("Simulated inbox response is outside the contract")
            raise InboxUnavailableError("banking-core sent an invalid inbox") from None
        return [
            InboxMessage(
                channel=m.channel,
                destination_masked=m.destination_masked,
                code=m.code,
                received_at=m.created_at,
                expires_at=m.expires_at,
            )
            for m in inbox.messages
        ]

    async def call_tool(
        self,
        session_id: str,
        tool_call: ToolCall | dict[str, Any],
    ) -> ToolResult:
        """Execute a tool call against banking-core with strict contract validation."""
        # Validate request with contracts model
        if not isinstance(tool_call, ToolCall):
            try:
                tool_call = ToolCall.model_validate(tool_call)
            except Exception as exc:
                logger.warning("ToolCall validation failed: %s", exc)
                # If tool name is present in raw dict and registered in catalog
                tool_name = tool_call.get("tool") if isinstance(tool_call, dict) else ""
                try:
                    return ToolResult(
                        tool=tool_name,
                        status=ToolResultStatus.ERROR,
                        reason_code=ReasonCode.INVALID_ARGUMENTS,
                        data=None,
                    )
                except Exception:
                    raise ValueError(f"Invalid ToolCall: {exc}") from exc

        client = self._get_client()
        url = f"{self.base_url}/v1/tools/call"
        headers = {"X-Session-Id": session_id}
        payload = tool_call.model_dump(mode="json")

        try:
            response = await client.post(url, headers=headers, json=payload)
            # Try to parse response body as contracts ToolResult even on non-200 status
            try:
                return ToolResult.model_validate(response.json())
            except Exception:
                # If response body cannot be parsed into ToolResult, map HTTP error
                logger.error(
                    "Banking-core returned unparseable response HTTP %s for tool %s",
                    response.status_code,
                    tool_call.tool,
                )
                return ToolResult(
                    tool=tool_call.tool,
                    status=ToolResultStatus.ERROR,
                    reason_code=ReasonCode.INTERNAL_ERROR,
                    data=None,
                )
        except httpx.TimeoutException:
            logger.error("Timeout executing tool '%s' on banking-core", tool_call.tool)
            return ToolResult(
                tool=tool_call.tool,
                status=ToolResultStatus.ERROR,
                reason_code=ReasonCode.INTERNAL_ERROR,
                data=None,
            )
        except httpx.RequestError as exc:
            logger.error(
                "Request error executing tool '%s' on banking-core: %s",
                tool_call.tool,
                exc,
            )
            return ToolResult(
                tool=tool_call.tool,
                status=ToolResultStatus.ERROR,
                reason_code=ReasonCode.INTERNAL_ERROR,
                data=None,
            )


class BankingCoreSyncClient:
    """Synchronous client wrapper for banking-core tools."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self.base_url = (base_url or cfg.banking_core_url).rstrip("/")
        self.timeout = (
            timeout if timeout is not None else cfg.banking_core_timeout_seconds
        )
        self._external_client = client
        self._client: httpx.Client | None = client

    def __enter__(self) -> "BankingCoreSyncClient":
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client and self._external_client is None:
            self._client.close()
            self._client = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    def close(self) -> None:
        """Close client if owned."""
        if self._client and self._external_client is None:
            self._client.close()
            self._client = None

    def create_session(self) -> str:
        """Issue POST /v1/sessions synchronously."""
        client = self._get_client()
        url = f"{self.base_url}/v1/sessions"
        try:
            response = client.post(url)
            response.raise_for_status()
            data = response.json()
            session_id = data.get("session_id")
            if not session_id or not isinstance(session_id, str):
                raise SessionCreationError(
                    f"Invalid session response from banking-core: {data}"
                )
            return session_id
        except Exception as exc:
            logger.error("Failed to create banking-core session: %s", exc)
            raise SessionCreationError(f"Session creation failed: {exc}") from exc

    def call_tool(
        self,
        session_id: str,
        tool_call: ToolCall | dict[str, Any],
    ) -> ToolResult:
        """Execute tool call synchronously with strict contract validation."""
        if not isinstance(tool_call, ToolCall):
            try:
                tool_call = ToolCall.model_validate(tool_call)
            except Exception as exc:
                tool_name = tool_call.get("tool") if isinstance(tool_call, dict) else ""
                try:
                    return ToolResult(
                        tool=tool_name,
                        status=ToolResultStatus.ERROR,
                        reason_code=ReasonCode.INVALID_ARGUMENTS,
                        data=None,
                    )
                except Exception:
                    raise ValueError(f"Invalid ToolCall: {exc}") from exc

        client = self._get_client()
        url = f"{self.base_url}/v1/tools/call"
        headers = {"X-Session-Id": session_id}
        payload = tool_call.model_dump(mode="json")

        try:
            response = client.post(url, headers=headers, json=payload)
            try:
                return ToolResult.model_validate(response.json())
            except Exception:
                logger.error(
                    "Banking-core returned unparseable response HTTP %s for tool %s",
                    response.status_code,
                    tool_call.tool,
                )
                return ToolResult(
                    tool=tool_call.tool,
                    status=ToolResultStatus.ERROR,
                    reason_code=ReasonCode.INTERNAL_ERROR,
                    data=None,
                )
        except httpx.TimeoutException:
            logger.error("Timeout executing tool '%s' on banking-core", tool_call.tool)
            return ToolResult(
                tool=tool_call.tool,
                status=ToolResultStatus.ERROR,
                reason_code=ReasonCode.INTERNAL_ERROR,
                data=None,
            )
        except httpx.RequestError as exc:
            logger.error(
                "Request error executing tool '%s' on banking-core: %s",
                tool_call.tool,
                exc,
            )
            return ToolResult(
                tool=tool_call.tool,
                status=ToolResultStatus.ERROR,
                reason_code=ReasonCode.INTERNAL_ERROR,
                data=None,
            )
