"""GET /v1/conversations/{id}/inbox: a relay of the conversation's own inbox."""

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import fakeredis
import httpx
import pytest
import respx
from fastapi import FastAPI
from orchestrator.config import Settings
from orchestrator.tools_client import (
    BankingCoreClient,
    InboxMessage,
    InboxUnavailableError,
)

from .fake_handler import FakeTurnHandler
from .test_chat_api import BANKING_URL, build_app

CODE = "482913"
OTHER_CODE = "915204"


def core_message(code: str = CODE, challenge_id: str = "chal_a1") -> dict[str, Any]:
    """banking-core's shape for one message."""
    return {
        "challenge_id": challenge_id,
        "channel": "EMAIL",
        "destination_masked": "d***@example.com",
        "code": code,
        "created_at": "2026-09-29T12:00:20Z",
        "expires_at": "2026-09-29T12:05:20Z",
    }


def inbox_url(banking_session_id: str) -> str:
    return f"{BANKING_URL}/v1/sessions/{banking_session_id}/simulated-inbox"


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis()


@pytest.fixture
def banking() -> Any:
    """banking-core: hands out sess_1, sess_2, ... to new conversations."""
    session_ids = iter(f"sess_opaque_{n:04d}" for n in range(1, 10))
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BANKING_URL}/v1/sessions").mock(
            side_effect=lambda request: httpx.Response(
                201, json={"session_id": next(session_ids)}
            )
        )
        yield router


@pytest.fixture
async def make_client() -> AsyncIterator[Callable[[FastAPI], httpx.AsyncClient]]:
    clients: list[httpx.AsyncClient] = []

    def _make(app: FastAPI) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://orch"
        )
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()


async def open_conversation(client: httpx.AsyncClient) -> str:
    created = await client.post("/v1/conversations", json={"lang": "es"})
    assert created.status_code == 201
    conversation_id: str = created.json()["conversation_id"]
    return conversation_id


async def test_the_inbox_relays_the_conversations_banking_session(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    route = banking.get(inbox_url("sess_opaque_0001")).mock(
        return_value=httpx.Response(200, json={"messages": [core_message()]})
    )
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = await open_conversation(client)

    response = await client.get(f"/v1/conversations/{conversation_id}/inbox")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "messages": [
            {
                "channel": "EMAIL",
                "destination_masked": "d***@example.com",
                "code": CODE,
                "received_at": "2026-09-29T12:00:20Z",
                "expires_at": "2026-09-29T12:05:20Z",
            }
        ]
    }
    assert route.call_count == 1


async def test_an_empty_inbox_is_an_empty_list(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    banking.get(inbox_url("sess_opaque_0001")).mock(
        return_value=httpx.Response(200, json={"messages": []})
    )
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = await open_conversation(client)

    response = await client.get(f"/v1/conversations/{conversation_id}/inbox")

    assert response.status_code == 200
    assert response.json() == {"messages": []}


async def test_a_conversation_can_only_ask_for_its_own_session(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    first = banking.get(inbox_url("sess_opaque_0001")).mock(
        return_value=httpx.Response(200, json={"messages": [core_message(CODE)]})
    )
    second = banking.get(inbox_url("sess_opaque_0002")).mock(
        return_value=httpx.Response(
            200, json={"messages": [core_message(OTHER_CODE, "chal_b1")]}
        )
    )
    client = make_client(build_app(redis, FakeTurnHandler()))
    mine = await open_conversation(client)
    theirs = await open_conversation(client)

    mine_inbox = await client.get(f"/v1/conversations/{mine}/inbox")
    theirs_inbox = await client.get(f"/v1/conversations/{theirs}/inbox")

    assert [m["code"] for m in mine_inbox.json()["messages"]] == [CODE]
    assert OTHER_CODE not in mine_inbox.text
    assert [m["code"] for m in theirs_inbox.json()["messages"]] == [OTHER_CODE]
    assert (first.call_count, second.call_count) == (1, 1)


async def test_an_unknown_conversation_is_a_404_and_banking_core_is_not_asked(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    route = banking.get(url__regex=r".*/simulated-inbox").mock(
        return_value=httpx.Response(200, json={"messages": [core_message()]})
    )
    client = make_client(build_app(redis, FakeTurnHandler()))

    response = await client.get("/v1/conversations/conv_unknown/inbox")

    assert response.status_code == 404
    assert CODE not in response.text
    assert route.call_count == 0


async def test_the_banking_core_session_id_is_never_a_path_parameter_of_ours(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    route = banking.get(url__regex=r".*/simulated-inbox").mock(
        return_value=httpx.Response(200, json={"messages": [core_message()]})
    )
    client = make_client(build_app(redis, FakeTurnHandler()))
    await open_conversation(client)

    for path in (
        "/v1/conversations/sess_opaque_0001/inbox",
        "/v1/sessions/sess_opaque_0001/simulated-inbox",
        "/v1/conversations/inbox",
    ):
        assert (await client.get(path)).status_code == 404
    assert route.call_count == 0


async def test_banking_core_saying_404_is_an_empty_inbox(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    banking.get(inbox_url("sess_opaque_0001")).mock(
        return_value=httpx.Response(404, json={"detail": "Session not found"})
    )
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = await open_conversation(client)

    response = await client.get(f"/v1/conversations/{conversation_id}/inbox")

    assert response.status_code == 200
    assert response.json() == {"messages": []}


@pytest.mark.parametrize(
    "answer",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.Response(500, text=f"boom {CODE}"),
        httpx.Response(200, json={"messages": [{"code": CODE}]}),
        httpx.Response(200, text=f'{{"messages": [{CODE}'),
    ],
    ids=["refused", "timeout", "http_500", "invalid_message", "truncated_json"],
)
async def test_banking_core_unavailable_is_a_503_that_does_not_echo_it(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: Any,
    answer: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    if isinstance(answer, Exception):
        banking.get(inbox_url("sess_opaque_0001")).mock(side_effect=answer)
    else:
        banking.get(inbox_url("sess_opaque_0001")).mock(return_value=answer)
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = await open_conversation(client)

    with caplog.at_level(logging.DEBUG):
        response = await client.get(f"/v1/conversations/{conversation_id}/inbox")

    assert response.status_code == 503
    assert response.json() == {"detail": "The inbox is temporarily unavailable"}
    assert CODE not in response.text
    assert CODE not in caplog.text


async def test_reading_the_inbox_never_lets_the_code_reach_state_or_logs(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    banking.get(inbox_url("sess_opaque_0001")).mock(
        return_value=httpx.Response(200, json={"messages": [core_message()]})
    )
    handler = FakeTurnHandler(reply="Te envié un código a tu correo.")
    app = build_app(redis, handler)
    client = make_client(app)
    conversation_id = await open_conversation(client)
    sent = await client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": "Perdí mi tarjeta, ayúdame a bloquearla"},
    )
    assert sent.status_code == 200
    stored_before = {key: await redis.get(key) for key in await redis.keys("*")}

    with caplog.at_level(logging.DEBUG):
        inbox = await client.get(f"/v1/conversations/{conversation_id}/inbox")
        transcript = await client.get(f"/v1/conversations/{conversation_id}")

    assert [m["code"] for m in inbox.json()["messages"]] == [CODE]
    # Nothing the read did changed what is stored (history, transcript, metadata).
    stored_after = {key: await redis.get(key) for key in await redis.keys("*")}
    assert stored_after == stored_before
    assert all(CODE.encode() not in value for value in stored_after.values() if value)
    state = await app.state.session_store.get(conversation_id)
    assert state is not None
    assert CODE not in state.model_dump_json()
    assert CODE not in str(state.llm_history)
    assert CODE not in transcript.text
    assert CODE not in sent.text
    assert CODE not in caplog.text
    assert handler.calls == [
        ("sess_opaque_0001", "Perdí mi tarjeta, ayúdame a bloquearla")
    ]


# --- BankingCoreClient.simulated_inbox ---------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings(banking_core_url=BANKING_URL, banking_core_timeout_seconds=2.0)


@respx.mock
async def test_client_maps_created_at_to_received_at(settings: Settings) -> None:
    respx.get(inbox_url("sess_x")).mock(
        return_value=httpx.Response(200, json={"messages": [core_message()]})
    )

    async with BankingCoreClient(settings=settings) as client:
        [message] = await client.simulated_inbox("sess_x")

    assert message.channel == "EMAIL"
    assert message.destination_masked == "d***@example.com"
    assert message.code == CODE
    assert message.received_at.isoformat() == "2026-09-29T12:00:20+00:00"
    assert message.expires_at.isoformat() == "2026-09-29T12:05:20+00:00"
    assert CODE not in repr(message)
    assert CODE not in str(message)


@respx.mock
async def test_client_quotes_the_session_id_into_one_path_segment(
    settings: Settings,
) -> None:
    route = respx.get(url__regex=r".*/simulated-inbox").mock(
        return_value=httpx.Response(200, json={"messages": []})
    )

    async with BankingCoreClient(settings=settings) as client:
        await client.simulated_inbox("sess_x/../other")

    assert route.calls.last.request.url.raw_path == (
        b"/v1/sessions/sess_x%2F..%2Fother/simulated-inbox"
    )


@respx.mock
async def test_client_errors_carry_no_payload(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    respx.get(inbox_url("sess_x")).mock(
        return_value=httpx.Response(200, json={"messages": [{"code": CODE}]})
    )

    async with BankingCoreClient(settings=settings) as client:
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(InboxUnavailableError) as raised:
                await client.simulated_inbox("sess_x")

    assert CODE not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert CODE not in caplog.text


def test_the_message_model_hides_the_code_in_its_repr() -> None:
    message = InboxMessage.model_validate(
        {
            "channel": "EMAIL",
            "destination_masked": "d***@example.com",
            "code": CODE,
            "received_at": "2026-09-29T12:00:20Z",
            "expires_at": "2026-09-29T12:05:20Z",
        }
    )

    assert CODE not in repr(message)
