"""POST /v1/conversations/{id}/feedback: a relay to the conversation's own session."""

from typing import Any

import fakeredis
import httpx
import pytest
from orchestrator.tools_client import FeedbackUnavailableError

from .fake_handler import FakeTurnHandler
from .test_chat_api import BANKING_URL, build_app
from .test_simulated_inbox import banking, make_client, open_conversation, redis

__all__ = ["banking", "make_client", "redis"]

RECORDED = {
    "handoff_ref": "hnd_abcd1234efgh",
    "helpful": True,
    "recorded_at": "2026-10-02T21:00:00Z",
}


def feedback_url(banking_session_id: str) -> str:
    return f"{BANKING_URL}/v1/sessions/{banking_session_id}/feedback"


async def test_the_answer_goes_to_the_conversations_banking_session(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    route = banking.post(feedback_url("sess_opaque_0001")).mock(
        return_value=httpx.Response(200, json=RECORDED)
    )
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = await open_conversation(client)

    response = await client.post(
        f"/v1/conversations/{conversation_id}/feedback", json={"helpful": True}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"helpful": True, "recorded_at": "2026-10-02T21:00:00Z"}
    assert "hnd_" not in response.text
    assert route.call_count == 1
    assert route.calls[0].request.read() == b'{"helpful":true}'


@pytest.mark.parametrize("reason", ["no_handoff", "already_answered"])
async def test_banking_cores_refusals_pass_through(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any, reason: str
) -> None:
    banking.post(feedback_url("sess_opaque_0001")).mock(
        return_value=httpx.Response(409, json={"detail": reason})
    )
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = await open_conversation(client)

    response = await client.post(
        f"/v1/conversations/{conversation_id}/feedback", json={"helpful": False}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": reason}


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(500, json={"detail": "boom"}),
        httpx.Response(409, json={"detail": "something_else"}),
        httpx.Response(200, json={"helpful": "yes"}),
        httpx.Response(200, text="not json"),
    ],
)
async def test_anything_else_from_banking_core_is_a_503(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: Any,
    answer: httpx.Response,
) -> None:
    banking.post(feedback_url("sess_opaque_0001")).mock(return_value=answer)
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = await open_conversation(client)

    response = await client.post(
        f"/v1/conversations/{conversation_id}/feedback", json={"helpful": True}
    )

    assert response.status_code == 503


async def test_an_unreachable_banking_core_is_a_503(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    banking.post(feedback_url("sess_opaque_0001")).mock(
        side_effect=httpx.ConnectError("down")
    )
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = await open_conversation(client)

    response = await client.post(
        f"/v1/conversations/{conversation_id}/feedback", json={"helpful": True}
    )

    assert response.status_code == 503
    assert FeedbackUnavailableError.__name__ not in response.text


async def test_an_unknown_conversation_is_a_404_and_banking_core_is_not_asked(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    route = banking.post(url__regex=r".*/feedback").mock(
        return_value=httpx.Response(200, json=RECORDED)
    )
    client = make_client(build_app(redis, FakeTurnHandler()))

    response = await client.post(
        "/v1/conversations/conv_unknown/feedback", json={"helpful": True}
    )

    assert response.status_code == 404
    assert route.call_count == 0


@pytest.mark.parametrize(
    "body", [{"helpful": "yes"}, {"helpful": 1}, {}, {"helpful": True, "x": 1}]
)
async def test_the_body_is_strict(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any, body: Any
) -> None:
    route = banking.post(url__regex=r".*/feedback").mock(
        return_value=httpx.Response(200, json=RECORDED)
    )
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = await open_conversation(client)

    response = await client.post(
        f"/v1/conversations/{conversation_id}/feedback", json=body
    )

    assert response.status_code == 422
    assert route.call_count == 0
