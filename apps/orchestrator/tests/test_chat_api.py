"""Chat API + redis-edge session store: fakeredis, fake handler, respx."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import fakeredis
import httpx
import pytest
import respx
from fastapi import FastAPI
from orchestrator.config import Settings
from orchestrator.main import create_app
from orchestrator.session.crypto import PlaceholderEncryptor
from orchestrator.session.store import SessionStore
from orchestrator.tools_client import BankingCoreClient

from .fake_handler import RECEIPT_BLOCK, FakeTurnHandler

BANKING_URL = "http://banking-core.test"
RAW_DOCUMENT = "1020304050"
RAW_NAME = "Carlos"


def build_app(
    redis: fakeredis.FakeAsyncRedis,
    handler: FakeTurnHandler | None,
    ttl_seconds: int = 3600,
) -> FastAPI:
    settings = Settings()
    store = SessionStore(
        redis=redis,
        encryptor=PlaceholderEncryptor("test-secret"),
        ttl_seconds=ttl_seconds,
        lock_timeout_seconds=30,
    )
    return create_app(
        settings=settings,
        session_store=store,
        banking_client=BankingCoreClient(base_url=BANKING_URL, settings=settings),
        turn_handler=handler,
    )


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis()


@pytest.fixture
def banking() -> Any:
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BANKING_URL}/v1/sessions").mock(
            return_value=httpx.Response(201, json={"session_id": "sess_opaque_0001"})
        )
        yield router


@pytest.fixture
async def make_client() -> AsyncIterator[Any]:
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


async def test_create_message_transcript_round_trip(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    handler = FakeTurnHandler(reply="Gracias {user}")
    client = make_client(build_app(redis, handler))

    created = await client.post("/v1/conversations", json={"lang": "pt"})
    assert created.status_code == 201
    body = created.json()
    conversation_id = body["conversation_id"]
    assert body == {"conversation_id": conversation_id, "language": "pt"}
    assert conversation_id.startswith("conv_")

    user_text = f"Me llamo {RAW_NAME}, mi cédula es {RAW_DOCUMENT}"
    sent = await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": user_text}
    )
    assert sent.status_code == 200
    assert sent.json()["blocks"][1] == RECEIPT_BLOCK
    assert handler.calls == [("sess_opaque_0001", user_text)]

    transcript = await client.get(f"/v1/conversations/{conversation_id}")
    assert transcript.status_code == 200
    data = transcript.json()
    assert data["language"] == "pt"
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert "[DOC_1]" in data["messages"][0]["content"]
    assert data["messages"][1]["blocks"] == [RECEIPT_BLOCK]

    # No raw PII anywhere in the transcript, nor internal state leaked
    dumped = transcript.text
    assert RAW_DOCUMENT not in dumped
    assert RAW_NAME not in dumped
    for internal in ("placeholder_map", "llm_history", "banking_session_id"):
        assert internal not in dumped
        assert internal not in created.text
        assert internal not in sent.text

    # At rest: the placeholder map is encrypted, raw PII never in redis-edge
    raw_state = await redis.get(f"orch:conv:{conversation_id}")
    assert RAW_DOCUMENT.encode() not in raw_state
    assert RAW_NAME.encode() not in raw_state
    assert json.loads(raw_state)["placeholder_map_enc"]


async def test_second_concurrent_turn_gets_409(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    gate = asyncio.Event()
    handler = FakeTurnHandler(gate=gate)
    client = make_client(build_app(redis, handler))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]
    url = f"/v1/conversations/{conversation_id}/messages"

    first = asyncio.create_task(client.post(url, json={"text": "hola"}))
    await asyncio.wait_for(handler.started.wait(), timeout=2)
    second = await client.post(url, json={"text": "hola otra vez"})
    gate.set()
    first_response = await first

    assert second.status_code == 409
    assert first_response.status_code == 200
    assert len(handler.calls) == 1

    # The lock is released after the turn: the next one goes through
    third = await client.post(url, json={"text": "tercera"})
    assert third.status_code == 200


async def test_expired_conversation_is_404(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), ttl_seconds=1))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]
    assert (await client.get(f"/v1/conversations/{conversation_id}")).status_code == 200

    await asyncio.sleep(1.2)

    assert (await client.get(f"/v1/conversations/{conversation_id}")).status_code == 404
    expired = await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": "hola"}
    )
    assert expired.status_code == 404


async def test_failed_turn_is_not_persisted_and_releases_lock(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    handler = FakeTurnHandler(fail=True)
    client = make_client(build_app(redis, handler))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]
    url = f"/v1/conversations/{conversation_id}/messages"

    failed = await client.post(url, json={"text": f"mi cédula es {RAW_DOCUMENT}"})
    assert failed.status_code == 503
    assert (await client.get(f"/v1/conversations/{conversation_id}")).json()[
        "messages"
    ] == []

    handler.fail = False
    assert (await client.post(url, json={"text": "hola"})).status_code == 200


async def test_without_turn_handler_messages_answer_503(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    client = make_client(build_app(redis, None))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]

    response = await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": "hola"}
    )

    assert response.status_code == 503
    assert "not wired" in response.json()["detail"]


async def test_unknown_conversation_and_bad_input(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler()))

    assert (await client.get("/v1/conversations/conv_missing")).status_code == 404
    missing = await client.post(
        "/v1/conversations/conv_missing/messages", json={"text": "hola"}
    )
    assert missing.status_code == 404
    bad_lang = await client.post("/v1/conversations", json={"lang": "fr"})
    assert bad_lang.status_code == 422


async def test_banking_session_failure_is_502(
    redis: fakeredis.FakeAsyncRedis, make_client: Any
) -> None:
    with respx.mock() as router:
        router.post(f"{BANKING_URL}/v1/sessions").mock(return_value=httpx.Response(500))
        client = make_client(build_app(redis, FakeTurnHandler()))
        response = await client.post("/v1/conversations")

    assert response.status_code == 502
    assert await redis.keys("orch:conv:*") == []


async def test_state_is_unreadable_with_another_secret(
    redis: fakeredis.FakeAsyncRedis,
) -> None:
    from orchestrator.session.models import ConversationState

    def store(secret: str) -> SessionStore:
        return SessionStore(
            redis=redis,
            encryptor=PlaceholderEncryptor(secret),
            ttl_seconds=60,
            lock_timeout_seconds=5,
        )

    state = ConversationState(
        banking_session_id="sess_1", placeholder_map={"[DOC_1]": RAW_DOCUMENT}
    )
    await store("secret-a").save(state)

    loaded = await store("secret-a").get(state.conversation_id)
    assert loaded is not None
    assert loaded.placeholder_map == {"[DOC_1]": RAW_DOCUMENT}
    assert await store("secret-b").get(state.conversation_id) is None
    assert 0 < await redis.ttl(f"orch:conv:{state.conversation_id}") <= 60


async def test_slow_turn_that_lost_its_lock_cannot_overwrite_a_newer_turn(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    gate = asyncio.Event()
    handler = FakeTurnHandler(reply="respuesta a {user}", gate=gate)
    store = SessionStore(
        redis=redis,
        encryptor=PlaceholderEncryptor("test-secret"),
        ttl_seconds=3600,
        lock_timeout_seconds=0.2,
    )
    settings = Settings()
    client = make_client(
        create_app(
            settings=settings,
            session_store=store,
            banking_client=BankingCoreClient(base_url=BANKING_URL, settings=settings),
            turn_handler=handler,
        )
    )
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]
    url = f"/v1/conversations/{conversation_id}/messages"

    slow = asyncio.create_task(client.post(url, json={"text": "turno lento"}))
    await asyncio.wait_for(handler.started.wait(), timeout=2)
    await asyncio.sleep(0.3)  # the slow turn's lock expires
    handler.gate = None  # the next turn runs straight through
    fast = await client.post(url, json={"text": "turno nuevo"})
    gate.set()
    slow_response = await slow

    assert fast.status_code == 200
    assert slow_response.status_code == 503
    assert "not saved" in slow_response.json()["detail"]
    state = await store.get(conversation_id)
    assert state is not None
    assert [m.content for m in state.messages] == [
        "turno nuevo",
        "respuesta a turno nuevo",
    ]
    assert state.llm_history == [{"role": "user", "content": "turno nuevo"}]


def test_startup_fails_without_session_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    for value in (None, "   "):
        if value is not None:
            monkeypatch.setenv("SESSION_SECRET", value)
        with pytest.raises(ValueError, match="SESSION_SECRET"):
            create_app(settings=Settings(_env_file=None))


def test_turn_lock_ttl_covers_the_slowest_turn_the_config_allows() -> None:
    settings = Settings(
        _env_file=None,
        LLM_TIMEOUT_SECONDS=30,
        LLM_MAX_RETRIES=2,
        MAX_TOOL_ROUNDS=5,
        SESSION_LOCK_MARGIN_SECONDS=60,
    )
    assert settings.turn_lock_seconds == 30 * 3 * 6 + 60


def test_access_log_never_records_the_conversation_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    create_app(
        session_store=SessionStore(
            redis=fakeredis.FakeAsyncRedis(),
            encryptor=PlaceholderEncryptor("x"),
            ttl_seconds=60,
            lock_timeout_seconds=5,
        )
    )
    conversation_id = "conv_" + "a1" * 16
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "POST",
            f"/v1/conversations/{conversation_id}/messages",
            "1.1",
            200,
        )

    assert conversation_id not in caplog.text
    assert "/v1/conversations/conv_[redacted]/messages" in caplog.text
