"""Agent API: auth, mounting, the session reverse index, takeover, agent messages.

The router is the human takeover's door into the untrusted zone. Every test here
runs the real app on fakeredis; nothing reaches an LLM, an encoder or a tool.
"""

import asyncio
import itertools
import json
import re
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import fakeredis
import httpx
import pytest
import respx
from fastapi import FastAPI
from orchestrator.agent.auth import DEVELOPMENT_AGENT_TOKEN, validate_agent_api_settings
from orchestrator.config import Settings
from orchestrator.main import create_app
from orchestrator.privacy.masking import MaskingError, RegexMasker
from orchestrator.session.crypto import CryptoError, PlaceholderEncryptor
from orchestrator.session.models import Message, MessageRole
from orchestrator.session.store import SessionStore
from orchestrator.tools_client import BankingCoreClient
from pydantic import ValidationError

from .fake_handler import FakeTurnHandler
from .test_chat_api import BANKING_URL, build_app

REPO_ROOT = Path(__file__).resolve().parents[3]
TOKEN = "test-only-agent-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ANA = "ana.agent@bank.example"
BEN = "ben.agent@bank.example"
HANDOFF = "hnd_abcdefghijklmnop"
RAW_DOCUMENT = "1020304050"
RAW_EMAIL = "carla.cliente@example.com"
CUSTOMER_EMAIL = "otro.cliente@example.com"
# An email, a name and a card number, in one agent message.
AGENT_TEXT = (
    f"Hola, soy Ana Gómez. Confirmo tu correo {RAW_EMAIL} "
    "y tu tarjeta 4111 1111 1111 1111."
)
AGENT_TEXT_MASKED = (
    "Hola, soy [NAME_1]. Confirmo tu correo [EMAIL_1] y tu tarjeta [CARD_1]."
)
# Pieces of AGENT_TEXT that cannot occur by chance inside a base64 ciphertext
# (each has a space, a dot, a comma or an @), so "not in Redis" has no false alarm.
AGENT_TEXT_PIECES = (
    "Hola, soy Ana",
    "soy Ana Gómez",
    "soy Ana G\\u00f3mez",  # the same name as a JSON \u escape
    RAW_EMAIL,
    "carla.cliente",
    "4111 1111 1111 1111",
    "4111 1111",
)

MakeClient = Callable[[FastAPI], httpx.AsyncClient]


def agent_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "agent_api_enabled": True,
        "agent_api_token": TOKEN,
        **overrides,
    }
    return Settings(**values)


def agent_headers(agent: str = ANA) -> dict[str, str]:
    return {**AUTH, "X-Agent-Ref": agent}


def message_body(
    text: str = "Hola, te atiende el equipo de disputas.", cid: str = "cmid-0000001"
) -> dict:
    return {"text": text, "client_message_id": cid}


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis()


@pytest.fixture
def banking() -> Any:
    """banking-core's POST /v1/sessions, one distinct session id per call."""
    counter = itertools.count(1)

    def open_session(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201, json={"session_id": f"sess_opaque_{next(counter):04d}"}
        )

    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BANKING_URL}/v1/sessions").mock(side_effect=open_session)
        yield router


@pytest.fixture
async def make_client() -> AsyncIterator[MakeClient]:
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
    return str(created.json()["conversation_id"])


async def take_over(
    client: httpx.AsyncClient, conversation_id: str, agent: str = ANA
) -> httpx.Response:
    return await client.post(
        f"/v1/agent/conversations/{conversation_id}/takeover",
        json={"agent_ref": agent, "handoff_ref": HANDOFF},
        headers=AUTH,
    )


@pytest.fixture
async def taken(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> tuple[httpx.AsyncClient, str, SessionStore]:
    """An app with the agent API on, and a conversation Ana already holds."""
    app = build_app(redis, FakeTurnHandler(), settings=agent_settings())
    client = make_client(app)
    conversation_id = await open_conversation(client)
    assert (await take_over(client, conversation_id)).status_code == 200
    return client, conversation_id, app.state.session_store


# ---------------------------------------------------------------- mounting, auth


async def test_agent_router_is_not_mounted_when_disabled(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = build_app(redis, FakeTurnHandler(), settings=Settings(_env_file=None))
    client = make_client(app)
    conversation_id = await open_conversation(client)

    for method, path in (
        ("GET", "/v1/agent/sessions/sess_opaque_0001/conversation"),
        ("GET", f"/v1/agent/conversations/{conversation_id}"),
        ("POST", f"/v1/agent/conversations/{conversation_id}/takeover"),
        ("POST", f"/v1/agent/conversations/{conversation_id}/messages"),
    ):
        response = await client.request(method, path, headers=AUTH, json={})
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}
    assert not [p for p in app.openapi()["paths"] if p.startswith("/v1/agent")]


async def test_agent_router_is_mounted_when_enabled(
    redis: fakeredis.FakeAsyncRedis, banking: Any
) -> None:
    app = build_app(redis, FakeTurnHandler(), settings=agent_settings())

    assert sorted(p for p in app.openapi()["paths"] if p.startswith("/v1/agent")) == [
        "/v1/agent/conversations/{conversation_id}",
        "/v1/agent/conversations/{conversation_id}/messages",
        "/v1/agent/conversations/{conversation_id}/release",
        "/v1/agent/conversations/{conversation_id}/takeover",
        "/v1/agent/sessions/{session_ref}/conversation",
    ]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": TOKEN},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": f"Bearer {TOKEN} "},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer é".encode("latin-1")},
    ],
    ids=[
        "none",
        "wrong",
        "no-scheme",
        "basic",
        "padded",
        "empty",
        "non-ascii",
    ],
)
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/v1/agent/sessions/sess_opaque_0001/conversation", None),
        ("GET", "/v1/agent/conversations/conv_x", None),
        (
            "POST",
            "/v1/agent/conversations/conv_x/takeover",
            {"agent_ref": ANA, "handoff_ref": HANDOFF},
        ),
        ("POST", "/v1/agent/conversations/conv_x/messages", message_body()),
        (
            "POST",
            "/v1/agent/conversations/conv_x/release",
            {"agent_ref": ANA, "handoff_ref": HANDOFF},
        ),
    ],
    ids=["session", "transcript", "takeover", "message", "release"],
)
async def test_agent_routes_answer_401_without_the_token(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: MakeClient,
    headers: dict[str, str | bytes],
    method: str,
    path: str,
    body: dict | None,
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))

    response = await client.request(
        method, path, headers={**headers, "X-Agent-Ref": ANA}, json=body
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid agent token"}


async def test_the_token_is_compared_in_constant_time(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: MakeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hmac as real_hmac

    original = real_hmac.compare_digest
    compared: list[tuple[bytes, bytes]] = []

    def spy(a: bytes, b: bytes) -> bool:
        compared.append((a, b))
        return original(a, b)

    monkeypatch.setattr("orchestrator.agent.auth.hmac.compare_digest", spy)
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))

    await client.get("/v1/agent/conversations/conv_x", headers=AUTH)

    assert compared == [(f"Bearer {TOKEN}".encode(), f"Bearer {TOKEN}".encode())]


async def test_the_token_is_not_the_admin_or_a_guessable_default(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))

    for token in (DEVELOPMENT_AGENT_TOKEN, "dev-only-admin-token", ""):
        response = await client.get(
            "/v1/agent/conversations/conv_x",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------- startup guard


@pytest.mark.parametrize(
    "app_env", ["production", "Production", " PRODUCTION "], ids=repr
)
@pytest.mark.parametrize(
    "token",
    [DEVELOPMENT_AGENT_TOKEN, f" {DEVELOPMENT_AGENT_TOKEN}\n"],
    ids=["exact", "padded"],
)
def test_startup_refuses_the_development_agent_token_in_production(
    app_env: str, token: str
) -> None:
    settings = agent_settings(app_env=app_env, agent_api_token=token)

    with pytest.raises(RuntimeError, match="public development token"):
        validate_agent_api_settings(settings)
    with pytest.raises(RuntimeError, match="public development token"):
        create_app(settings=settings)


@pytest.mark.parametrize("app_env", ["production", "development"])
@pytest.mark.parametrize("token", ["", "   ", "\n"], ids=["empty", "blank", "newline"])
def test_startup_refuses_an_empty_agent_token_anywhere(
    app_env: str, token: str
) -> None:
    settings = agent_settings(app_env=app_env, agent_api_token=token)

    with pytest.raises(RuntimeError, match="AGENT_API_TOKEN is required"):
        validate_agent_api_settings(settings)
    with pytest.raises(RuntimeError, match="AGENT_API_TOKEN is required"):
        create_app(settings=settings)


def test_startup_refuses_the_enabled_api_with_no_token_at_all() -> None:
    settings = Settings(_env_file=None, agent_api_enabled=True)

    with pytest.raises(RuntimeError, match="AGENT_API_TOKEN is required"):
        validate_agent_api_settings(settings)


@pytest.mark.parametrize(
    ("app_env", "enabled", "token"),
    [
        ("development", True, DEVELOPMENT_AGENT_TOKEN),
        ("production", True, "a-real-secret-from-the-platform"),
        ("production", False, DEVELOPMENT_AGENT_TOKEN),
        ("production", False, ""),
        ("development", False, ""),
    ],
    ids=[
        "development-accepts-the-development-token",
        "production-accepts-its-own-secret",
        "production-with-the-api-off-uses-no-token",
        "production-with-the-api-off-and-no-token",
        "development-with-the-api-off-and-no-token",
    ],
)
def test_startup_accepts_the_agent_settings_that_are_safe(
    app_env: str, enabled: bool, token: str
) -> None:
    validate_agent_api_settings(
        agent_settings(
            app_env=app_env, agent_api_enabled=enabled, agent_api_token=token
        )
    )


def test_the_agent_api_is_off_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.agent_api_enabled is False
    assert settings.effective_agent_api_token == ""
    assert TOKEN not in repr(agent_settings())


def test_compose_default_agent_token_is_the_one_production_refuses() -> None:
    """If the compose default drifts, the production guard silently stops matching."""
    compose = (REPO_ROOT / "infra/compose/docker-compose.yml").read_text()
    env_example = (REPO_ROOT / ".env.example").read_text()

    # The orchestrator, and web-backoffice, which sends the token it expects.
    assert re.findall(r"AGENT_API_TOKEN: \$\{AGENT_API_TOKEN:-([^}]*)\}", compose) == [
        DEVELOPMENT_AGENT_TOKEN,
        DEVELOPMENT_AGENT_TOKEN,
    ]
    assert re.findall(
        r"AGENT_API_ENABLED: \$\{AGENT_API_ENABLED:-([^}]*)\}", compose
    ) == ["true"]
    assert re.findall(r"^AGENT_API_TOKEN=(.*)$", env_example, re.MULTILINE) == [
        DEVELOPMENT_AGENT_TOKEN
    ]


def test_the_production_overlay_switches_the_agent_api_off_by_default() -> None:
    """The base file enables it with a public token; production must not inherit it."""
    prod = (REPO_ROOT / "infra/compose/docker-compose.prod.yml").read_text()

    assert re.findall(r"AGENT_API_ENABLED: \$\{AGENT_API_ENABLED:-([^}]*)\}", prod) == [
        "false"
    ]
    assert re.findall(r"AGENT_API_TOKEN: \$\{AGENT_API_TOKEN:-([^}]*)\}", prod) == [""]
    # The back office has no default there: unset is a compose error.
    assert len(re.findall(r"AGENT_API_TOKEN: \$\{AGENT_API_TOKEN:\?[^}]+\}", prod)) == 1


# ---------------------------------------------------------------- reverse index


async def test_the_reverse_index_is_written_when_the_conversation_is_created(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(
        build_app(redis, FakeTurnHandler(), ttl_seconds=120, settings=agent_settings())
    )

    conversation_id = await open_conversation(client)

    assert await redis.get("orch:session:sess_opaque_0001") == conversation_id.encode()
    index_ttl = await redis.ttl("orch:session:sess_opaque_0001")
    conversation_ttl = await redis.ttl(f"orch:conv:{conversation_id}")
    assert 0 < index_ttl <= 120
    assert abs(index_ttl - conversation_ttl) <= 1
    # One entry per conversation, holding the opaque id and nothing else.
    assert [k.decode() for k in await redis.keys("orch:session:*")] == [
        "orch:session:sess_opaque_0001"
    ]


async def test_a_saved_turn_refreshes_the_index_with_the_conversation(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(
        build_app(redis, FakeTurnHandler(), ttl_seconds=120, settings=agent_settings())
    )
    conversation_id = await open_conversation(client)
    await redis.expire("orch:session:sess_opaque_0001", 5)
    await redis.expire(f"orch:conv:{conversation_id}", 5)

    await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": "hola"}
    )

    for key in (f"orch:conv:{conversation_id}", "orch:session:sess_opaque_0001"):
        assert 100 < await redis.ttl(key) <= 120
    # An index lost before the save is written back.
    await redis.delete("orch:session:sess_opaque_0001")
    await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": "otra vez"}
    )
    assert await redis.get("orch:session:sess_opaque_0001") == conversation_id.encode()


async def test_the_session_ref_resolves_to_its_conversation(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))
    first = await open_conversation(client)
    second = await open_conversation(client)

    one = await client.get(
        "/v1/agent/sessions/sess_opaque_0001/conversation", headers=AUTH
    )
    two = await client.get(
        "/v1/agent/sessions/sess_opaque_0002/conversation", headers=AUTH
    )

    assert one.status_code == two.status_code == 200
    assert one.json() == {"conversation_id": first}
    assert two.json() == {"conversation_id": second}


@pytest.mark.parametrize(
    "session_ref",
    ["sess_unknown", "conv_x", "sess_opaque_0001" + "x" * 200, "%20", "a:b"],
    ids=["unknown", "a-conversation-id", "too-long", "blank", "colon"],
)
async def test_an_unknown_session_ref_is_404(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: MakeClient,
    session_ref: str,
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))
    await open_conversation(client)

    response = await client.get(
        f"/v1/agent/sessions/{session_ref}/conversation", headers=AUTH
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


async def test_a_stale_or_foreign_index_entry_does_not_answer(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))
    first = await open_conversation(client)
    await open_conversation(client)
    url = "/v1/agent/sessions/{}/conversation"

    # The conversation is gone but its index entry is not: nothing to answer.
    await redis.delete(f"orch:conv:{first}")
    gone = await client.get(url.format("sess_opaque_0001"), headers=AUTH)
    # An entry that points at another session's conversation is not believed.
    await redis.set(
        "orch:session:sess_forged", (await redis.keys("orch:conv:*"))[0][10:]
    )
    forged = await client.get(url.format("sess_forged"), headers=AUTH)

    assert gone.status_code == 404
    assert forged.status_code == 404


# ---------------------------------------------------------------- takeover


async def test_takeover_of_an_unknown_conversation_is_404(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))

    response = await take_over(client, "conv_" + "0" * 32)

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


async def test_takeover_records_who_and_since_when(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = build_app(redis, FakeTurnHandler(), settings=agent_settings())
    client = make_client(app)
    conversation_id = await open_conversation(client)

    response = await take_over(client, conversation_id)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"conversation_id", "takeover"}
    assert body["conversation_id"] == conversation_id
    assert set(body["takeover"]) == {"active", "since", "agent_ref"}
    assert body["takeover"]["active"] is True
    assert body["takeover"]["agent_ref"] == ANA
    assert datetime.fromisoformat(body["takeover"]["since"]).tzinfo is not None
    state = await app.state.session_store.get(conversation_id)
    assert state.takeover.active and state.takeover.agent_ref == ANA


async def test_takeover_is_idempotent_for_the_same_agent(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    before = await store.get(conversation_id)

    again = await take_over(client, conversation_id, ANA)

    assert again.status_code == 200
    assert again.json()["takeover"]["agent_ref"] == ANA
    assert (
        datetime.fromisoformat(again.json()["takeover"]["since"])
        == before.takeover.since
    )
    after = await store.get(conversation_id)
    assert after.takeover == before.takeover
    assert after.updated_at == before.updated_at


async def test_another_agent_cannot_take_a_held_conversation(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    before = await store.get(conversation_id)

    response = await take_over(client, conversation_id, BEN)

    assert response.status_code == 409
    assert response.json() == {"detail": "taken_over_by_another_agent"}
    assert (await store.get(conversation_id)).takeover == before.takeover


@pytest.mark.parametrize(
    "body",
    [
        {"agent_ref": ANA},
        {"handoff_ref": HANDOFF},
        {"agent_ref": "ab", "handoff_ref": HANDOFF},
        {"agent_ref": "a" * 255, "handoff_ref": HANDOFF},
        {"agent_ref": "ana agent@bank.example", "handoff_ref": HANDOFF},
        {"agent_ref": ANA, "handoff_ref": ""},
        {"agent_ref": ANA, "handoff_ref": "hnd bad"},
        {"agent_ref": ANA, "handoff_ref": HANDOFF, "extra": 1},
        {"agent_ref": None, "handoff_ref": HANDOFF},
    ],
    ids=[
        "no-handoff",
        "no-agent",
        "short-agent",
        "long-agent",
        "agent-with-space",
        "empty-handoff",
        "handoff-with-space",
        "extra-field",
        "null-agent",
    ],
)
async def test_takeover_rejects_a_malformed_body(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: MakeClient,
    body: dict[str, Any],
) -> None:
    app = build_app(redis, FakeTurnHandler(), settings=agent_settings())
    client = make_client(app)
    conversation_id = await open_conversation(client)

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/takeover", json=body, headers=AUTH
    )

    assert response.status_code == 422
    assert not (await app.state.session_store.get(conversation_id)).takeover.active


async def test_takeover_waits_for_a_customer_turn_and_is_not_overwritten_by_it(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    gate = asyncio.Event()
    handler = FakeTurnHandler(gate=gate)
    app = build_app(redis, handler, settings=agent_settings(agent_lock_wait_seconds=5))
    client = make_client(app)
    conversation_id = await open_conversation(client)
    turn = asyncio.create_task(
        client.post(
            f"/v1/conversations/{conversation_id}/messages", json={"text": "hola"}
        )
    )
    await asyncio.wait_for(handler.started.wait(), timeout=2)

    takeover = asyncio.create_task(take_over(client, conversation_id))
    await asyncio.sleep(0.2)
    assert not takeover.done()  # waiting for the turn's lock, not failing
    gate.set()
    turn_response, takeover_response = await asyncio.gather(turn, takeover)

    assert turn_response.status_code == 200
    assert takeover_response.status_code == 200
    state = await app.state.session_store.get(conversation_id)
    # The turn was saved whole, and the takeover landed after it.
    assert [m.role.value for m in state.messages] == ["user", "assistant"]
    assert state.takeover.active and state.takeover.agent_ref == ANA


async def test_takeover_answers_503_when_a_turn_outlasts_the_wait(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    gate = asyncio.Event()
    handler = FakeTurnHandler(gate=gate)
    app = build_app(
        redis, handler, settings=agent_settings(agent_lock_wait_seconds=0.2)
    )
    client = make_client(app)
    conversation_id = await open_conversation(client)
    turn = asyncio.create_task(
        client.post(
            f"/v1/conversations/{conversation_id}/messages", json={"text": "hola"}
        )
    )
    await asyncio.wait_for(handler.started.wait(), timeout=2)

    response = await take_over(client, conversation_id)
    gate.set()
    await turn

    assert response.status_code == 503
    assert response.json() == {"detail": "turn_in_progress"}
    assert response.headers["retry-after"] == "2"
    # Nothing was written, and the retry that follows succeeds.
    assert not (await app.state.session_store.get(conversation_id)).takeover.active
    assert (await take_over(client, conversation_id)).status_code == 200


async def test_after_a_takeover_the_turn_lock_is_free(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    _, conversation_id, store = taken

    token = await store.acquire_turn_lock(conversation_id)

    assert token is not None


# ---------------------------------------------------------------- agent messages


async def release(
    client: httpx.AsyncClient, conversation_id: str, agent: str = ANA
) -> httpx.Response:
    return await client.post(
        f"/v1/agent/conversations/{conversation_id}/release",
        json={"agent_ref": agent, "handoff_ref": HANDOFF},
        headers=AUTH,
    )


async def test_the_holder_releases_and_the_assistant_stays_off(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    before = await store.get(conversation_id)

    response = await release(client, conversation_id)

    assert response.status_code == 200
    assert response.json()["takeover"]["active"] is True
    assert response.json()["takeover"]["agent_ref"] is None
    after = await store.get(conversation_id)
    assert after.takeover.active is True
    assert after.takeover.agent_ref is None
    assert after.takeover.since == before.takeover.since


async def test_after_a_release_another_agent_takes_the_conversation(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    assert (await release(client, conversation_id)).status_code == 200

    response = await take_over(client, conversation_id, BEN)

    assert response.status_code == 200
    assert response.json()["takeover"]["agent_ref"] == BEN
    assert (await store.get(conversation_id)).takeover.agent_ref == BEN


async def test_after_a_release_nobody_writes_until_someone_takes_it(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    await release(client, conversation_id)

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body(),
        headers=agent_headers(),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "no_active_takeover"}


async def test_only_the_holder_may_release(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    before = await store.get(conversation_id)

    response = await release(client, conversation_id, BEN)

    assert response.status_code == 409
    assert response.json() == {"detail": "taken_over_by_another_agent"}
    assert (await store.get(conversation_id)).takeover == before.takeover


async def test_releasing_what_nobody_holds_changes_nothing(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = build_app(redis, FakeTurnHandler(), settings=agent_settings())
    client = make_client(app)
    conversation_id = await open_conversation(client)
    store = app.state.session_store
    before = await store.get(conversation_id)

    never_taken = await release(client, conversation_id)
    await take_over(client, conversation_id)
    await release(client, conversation_id)
    released = await store.get(conversation_id)
    again = await release(client, conversation_id, BEN)

    assert never_taken.status_code == 200
    assert never_taken.json()["takeover"] == {
        "active": False,
        "since": None,
        "agent_ref": None,
    }
    assert before.takeover.active is False
    assert again.status_code == 200
    assert (await store.get(conversation_id)).updated_at == released.updated_at


async def test_release_of_an_unknown_conversation_is_404(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))

    response = await release(client, "conv_" + "0" * 32)

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"agent_ref": ANA},
        {"handoff_ref": HANDOFF},
        {"agent_ref": ANA, "handoff_ref": HANDOFF, "x": 1},
    ],
    ids=["no-handoff", "no-agent", "extra-field"],
)
async def test_release_rejects_a_malformed_body(
    taken: tuple[httpx.AsyncClient, str, SessionStore], body: dict[str, Any]
) -> None:
    client, conversation_id, store = taken

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/release", json=body, headers=AUTH
    )

    assert response.status_code == 422
    assert (await store.get(conversation_id)).takeover.agent_ref == ANA


async def test_an_agent_message_needs_a_takeover(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = build_app(redis, FakeTurnHandler(), settings=agent_settings())
    client = make_client(app)
    conversation_id = await open_conversation(client)

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body(),
        headers=agent_headers(),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "no_active_takeover"}
    assert (await app.state.session_store.get(conversation_id)).messages == []


@pytest.mark.parametrize(
    "agent", [BEN, "ANA.AGENT@bank.example"], ids=["other", "case"]
)
async def test_only_the_agent_who_holds_the_conversation_may_write(
    taken: tuple[httpx.AsyncClient, str, SessionStore], agent: str
) -> None:
    client, conversation_id, store = taken

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body(),
        headers=agent_headers(agent),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "no_active_takeover"}
    assert (await store.get(conversation_id)).messages == []


async def test_an_agent_message_without_the_agent_header_is_refused(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body(),
        headers=AUTH,
    )

    assert response.status_code == 422
    assert (await store.get(conversation_id)).messages == []


async def test_an_agent_message_to_an_unknown_conversation_is_404(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))

    response = await client.post(
        "/v1/agent/conversations/conv_" + "0" * 32 + "/messages",
        json=message_body(),
        headers=agent_headers(),
    )

    assert response.status_code == 404


async def test_an_agent_message_is_stored_and_returned(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body("  Hola. Reviso tu caso ahora mismo.  "),
        headers=agent_headers(),
    )

    assert response.status_code == 200
    message = response.json()["message"]
    assert set(response.json()) == {"message"}
    assert set(message) == {"role", "content", "blocks", "created_at"}
    assert message["role"] == "agent"
    assert message["content"] == "Hola. Reviso tu caso ahora mismo."
    assert message["blocks"] == []
    state = await store.get(conversation_id)
    assert [(m.role.value, m.content) for m in state.messages] == [
        ("agent", "Hola. Reviso tu caso ahora mismo.")
    ]


async def test_agent_text_is_masked_before_it_is_stored(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    """What is stored in clear is masked; the answer is the text as written."""
    client, conversation_id, store = taken
    text = f"Confirmo tu correo {RAW_EMAIL} y tu tarjeta 4111 1111 1111 1111."

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body(text),
        headers=agent_headers(),
    )

    assert response.status_code == 200
    assert response.json()["message"]["content"] == text
    state = await store.get(conversation_id)
    assert [m.content for m in state.messages] == [
        "Confirmo tu correo [EMAIL_1] y tu tarjeta [CARD_1]."
    ]
    # Not in what Redis holds: the masked text is stored in clear, the text as
    # written only as ciphertext (test_agent_text_as_written.py goes further).
    stored = await store.redis.get(f"orch:conv:{conversation_id}")
    assert RAW_EMAIL.encode() not in stored and b"4111 1111" not in stored
    # The raw values live only in the encrypted placeholder map.
    assert state.placeholder_map["[EMAIL_1]"] == RAW_EMAIL


async def test_a_name_the_agent_introduces_reaches_the_customer_as_written(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    """ADR-0013, amendment 2026-09-29: "soy Ana" no longer reads "soy [NAME_1]"."""
    client, conversation_id, store = taken

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body("Hola, soy Ana."),
        headers=agent_headers(),
    )

    assert response.json()["message"]["content"] == "Hola, soy Ana."
    customer_view = (await client.get(f"/v1/conversations/{conversation_id}")).json()
    assert customer_view["messages"][0]["content"] == "Hola, soy Ana."
    # The stored, clear-text twin stays masked.
    assert (await store.get(conversation_id)).messages[
        0
    ].content == "Hola, soy [NAME_1]."


async def test_agent_text_shares_the_conversations_placeholders(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    state = await store.get(conversation_id)
    state.placeholder_map["[DOC_1]"] = RAW_DOCUMENT
    await store.save(state)

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body(f"Veo la cédula {RAW_DOCUMENT} en tu perfil."),
        headers=agent_headers(),
    )

    # Masked with the conversation's own placeholder; the answer is as written.
    assert response.json()["message"]["content"] == (
        f"Veo la cédula {RAW_DOCUMENT} en tu perfil."
    )
    state = await store.get(conversation_id)
    assert state.messages[0].content == "Veo la cédula [DOC_1] en tu perfil."


async def test_agent_text_fails_closed_to_redacted(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, conversation_id, store = taken

    class BrokenMasker(RegexMasker):
        def mask(self, text: str, state: dict[str, str] | None = None) -> Any:
            raise MaskingError("boom")

    monkeypatch.setattr("orchestrator.agent.routes.TRANSCRIPT_MASKER", BrokenMasker())

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body(f"cédula {RAW_DOCUMENT}"),
        headers=agent_headers(),
    )

    assert response.status_code == 200
    # The stored twin fails closed; the text as written is not affected by it.
    assert response.json()["message"]["content"] == f"cédula {RAW_DOCUMENT}"
    assert (await store.get(conversation_id)).messages[0].content == "[REDACTED]"
    assert RAW_DOCUMENT.encode() not in await store.redis.get(
        f"orch:conv:{conversation_id}"
    )


async def test_a_repeated_client_message_id_returns_the_stored_message(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    url = f"/v1/agent/conversations/{conversation_id}/messages"

    first = await client.post(
        url, json=message_body("Primero"), headers=agent_headers()
    )
    repeat = await client.post(
        url, json=message_body("Primero"), headers=agent_headers()
    )
    changed = await client.post(
        url, json=message_body("Otro texto"), headers=agent_headers()
    )
    fresh = await client.post(
        url, json=message_body("Segundo", cid="cmid-0000002"), headers=agent_headers()
    )

    assert first.status_code == repeat.status_code == changed.status_code == 200
    assert repeat.json() == first.json() == changed.json()
    assert fresh.json()["message"]["content"] == "Segundo"
    state = await store.get(conversation_id)
    assert [m.content for m in state.messages] == ["Primero", "Segundo"]


async def test_a_retry_after_customer_messages_still_returns_the_stored_message(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    url = f"/v1/agent/conversations/{conversation_id}/messages"
    first = await client.post(
        url, json=message_body("Primero"), headers=agent_headers()
    )
    await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": "gracias"}
    )

    repeat = await client.post(
        url, json=message_body("Primero"), headers=agent_headers()
    )

    assert repeat.json() == first.json()
    assert [m.role.value for m in (await store.get(conversation_id)).messages] == [
        "agent",
        "user",
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"text": "", "client_message_id": "cmid-0000001"},
        {"text": "   \n ", "client_message_id": "cmid-0000001"},
        {"text": "x" * 2001, "client_message_id": "cmid-0000001"},
        {"text": "hola"},
        {"client_message_id": "cmid-0000001"},
        {"text": "hola", "client_message_id": "short"},
        {"text": "hola", "client_message_id": "has space 123"},
        {"text": "hola", "client_message_id": "c" * 65},
        {"text": "hola", "client_message_id": "cmid-0000001", "role": "user"},
    ],
    ids=[
        "empty",
        "blank",
        "too-long",
        "no-id",
        "no-text",
        "short-id",
        "id-with-space",
        "long-id",
        "extra-field",
    ],
)
async def test_an_agent_message_rejects_a_malformed_body(
    taken: tuple[httpx.AsyncClient, str, SessionStore], body: dict[str, Any]
) -> None:
    client, conversation_id, store = taken

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=body,
        headers=agent_headers(),
    )

    assert response.status_code == 422
    assert (await store.get(conversation_id)).messages == []


async def test_the_longest_agent_message_is_accepted(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, _ = taken

    response = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body("x" * 2000),
        headers=agent_headers(),
    )

    assert response.status_code == 200


# ------------------------------------------------ agent text, as written (ADR-0013)


def messages_url(conversation_id: str) -> str:
    return f"/v1/agent/conversations/{conversation_id}/messages"


READS = ("/v1/agent/conversations/{}", "/v1/conversations/{}")


async def post_agent_text(
    client: httpx.AsyncClient,
    conversation_id: str,
    text: str = AGENT_TEXT,
    cid: str = "cmid-0000001",
) -> httpx.Response:
    return await client.post(
        messages_url(conversation_id),
        json=message_body(text, cid),
        headers=agent_headers(),
    )


async def stored_json(store: SessionStore, conversation_id: str) -> dict[str, Any]:
    raw = await store.redis.get(f"orch:conv:{conversation_id}")
    assert raw is not None
    return dict(json.loads(raw))


async def rewrite_message_field(
    store: SessionStore,
    conversation_id: str,
    field: str,
    value: Any,
    index: int = 0,
    remove: bool = False,
) -> None:
    """Edit one stored message in Redis by hand: what an old or damaged value is."""
    key = f"orch:conv:{conversation_id}"
    payload = await stored_json(store, conversation_id)
    if remove:
        del payload["messages"][index][field]
    else:
        payload["messages"][index][field] = value
    await store.redis.set(key, json.dumps(payload), keepttl=True)


async def test_the_text_as_written_is_not_in_redis_in_clear(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken

    response = await post_agent_text(client, conversation_id)

    assert response.status_code == 200
    raw = await store.redis.get(f"orch:conv:{conversation_id}")
    for piece in AGENT_TEXT_PIECES:
        assert piece.encode() not in raw, piece
    message = (await stored_json(store, conversation_id))["messages"][0]
    # The clear field is the masked twin; the text as written is a Fernet token.
    assert message["content"] == AGENT_TEXT_MASKED
    assert message["content_enc"].startswith("gAAAA")
    assert message["content_enc"] != AGENT_TEXT
    assert store.encryptor.decrypt_text(message["content_enc"]) == AGENT_TEXT
    # Every string the state holds in clear is free of the raw values.
    assert not any(piece in json.dumps(message) for piece in AGENT_TEXT_PIECES)


async def test_the_stored_text_is_the_one_that_passed_the_strip(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken

    response = await post_agent_text(client, conversation_id, "  \n Hola, soy Ana.  \n")

    assert response.json()["message"]["content"] == "Hola, soy Ana."
    stored = (await store.get(conversation_id)).messages[0]
    assert store.encryptor.decrypt_text(stored.content_enc) == "Hola, soy Ana."


async def test_only_agent_messages_carry_the_text_as_written(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = build_app(redis, FakeTurnHandler(), settings=agent_settings())
    client = make_client(app)
    store: SessionStore = app.state.session_store
    conversation_id = await open_conversation(client)
    messages = f"/v1/conversations/{conversation_id}/messages"
    await client.post(messages, json={"text": f"Mi correo es {CUSTOMER_EMAIL}"})
    await take_over(client, conversation_id)
    await post_agent_text(client, conversation_id)
    await client.post(messages, json={"text": "Gracias"})

    stored = (await stored_json(store, conversation_id))["messages"]

    assert [(m["role"], m["content_enc"] is not None) for m in stored] == [
        ("user", False),
        ("assistant", False),
        ("agent", True),
        ("user", False),
    ]
    raw = await store.redis.get(f"orch:conv:{conversation_id}")
    assert CUSTOMER_EMAIL.encode() not in raw


@pytest.mark.parametrize(
    "role", [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.SYSTEM]
)
def test_a_message_that_is_not_the_agents_cannot_carry_the_text(
    role: MessageRole,
) -> None:
    with pytest.raises(ValidationError):
        Message(role=role, content="hola", content_enc="gAAAAA-anything")

    assert Message(role=role, content="hola").content_enc is None
    assert Message(role=MessageRole.AGENT, content="hola", content_enc="x").content_enc


async def test_both_reads_return_the_text_as_the_agent_wrote_it(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, _ = taken
    await post_agent_text(client, conversation_id)
    await client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": f"Mi correo es {CUSTOMER_EMAIL}"},
    )

    for template in READS:
        response = await client.get(template.format(conversation_id), headers=AUTH)

        assert response.status_code == 200
        shown = response.json()["messages"]
        # The agent's text as written; the customer's own message still masked.
        assert [(m["role"], m["content"]) for m in shown] == [
            ("agent", AGENT_TEXT),
            ("user", "Mi correo es [EMAIL_2]"),
        ]
        assert CUSTOMER_EMAIL not in response.text
        # The shape is what it was: no new field, no ciphertext anywhere.
        for message in shown:
            assert set(message) == {"role", "content", "blocks", "created_at"}
        assert "content_enc" not in response.text
        assert "gAAAA" not in response.text


async def test_the_answer_to_a_write_is_the_text_as_written_in_the_same_shape(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, _ = taken

    response = await post_agent_text(client, conversation_id)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message"}
    assert set(body["message"]) == {"role", "content", "blocks", "created_at"}
    assert body["message"]["content"] == AGENT_TEXT
    assert "content_enc" not in response.text and "gAAAA" not in response.text
    # What the write answered is what a read shows.
    read = (await client.get(READS[0].format(conversation_id), headers=AUTH)).json()
    assert read["messages"] == [body["message"]]


async def test_the_replay_of_a_write_returns_the_text_as_written_and_stores_nothing(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, store = taken
    first = await post_agent_text(client, conversation_id)
    stored_before = (await stored_json(store, conversation_id))["messages"]

    same = await post_agent_text(client, conversation_id)
    changed = await post_agent_text(client, conversation_id, "Otro texto de Ana")

    assert first.status_code == same.status_code == changed.status_code == 200
    assert first.json()["message"]["content"] == AGENT_TEXT
    # The replay is the stored message, whatever text the retry carries.
    assert same.json() == first.json() == changed.json()
    # One message, one ciphertext: the retry did not encrypt or write again.
    assert (await stored_json(store, conversation_id))["messages"] == stored_before
    assert (
        "Otro texto"
        not in (await store.redis.get(f"orch:conv:{conversation_id}")).decode()
    )


async def test_the_replay_after_the_customer_wrote_still_gives_the_text_as_written(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
) -> None:
    client, conversation_id, _ = taken
    first = await post_agent_text(client, conversation_id)
    await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": "gracias"}
    )

    repeat = await post_agent_text(client, conversation_id)

    assert repeat.json() == first.json()
    assert repeat.json()["message"]["content"] == AGENT_TEXT


CORRUPTIONS = {
    "garbage": lambda good: "this-is-not-a-fernet-token",
    "empty": lambda good: "",
    "tampered": lambda good: good[:-8] + ("A" if good[-8] != "A" else "B") + good[-7:],
    "another-secret": lambda good: PlaceholderEncryptor("not-our-secret").encrypt_text(
        AGENT_TEXT
    ),
}


@pytest.mark.parametrize("corruption", list(CORRUPTIONS))
async def test_a_ciphertext_that_cannot_be_read_falls_back_to_the_masked_text(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
    caplog: pytest.LogCaptureFixture,
    corruption: str,
) -> None:
    client, conversation_id, store = taken
    await post_agent_text(client, conversation_id)
    good = (await stored_json(store, conversation_id))["messages"][0]["content_enc"]
    bad = CORRUPTIONS[corruption](good)
    await rewrite_message_field(store, conversation_id, "content_enc", bad)
    caplog.clear()

    with caplog.at_level("DEBUG"):
        reads = [
            await client.get(template.format(conversation_id), headers=AUTH)
            for template in READS
        ]
        replay = await post_agent_text(client, conversation_id)

    # Never a 5xx: the masked text stands in, on every route that shows the text.
    for response in reads:
        assert response.status_code == 200
        assert [m["content"] for m in response.json()["messages"]] == [
            AGENT_TEXT_MASKED
        ]
    assert replay.status_code == 200
    assert replay.json()["message"]["content"] == AGENT_TEXT_MASKED
    # A warning was logged, and neither the text nor a ciphertext is in any record.
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (*AGENT_TEXT_PIECES, good, bad):
        if secret:
            assert secret not in logged, secret
    # The conversation is still usable afterwards.
    again = await post_agent_text(client, conversation_id, "Sigo aquí", "cmid-0000002")
    assert again.status_code == 200
    assert again.json()["message"]["content"] == "Sigo aquí"


@pytest.mark.parametrize("as_stored", ["missing", "null"])
async def test_a_message_stored_before_the_field_existed_reads_as_it_always_did(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
    caplog: pytest.LogCaptureFixture,
    as_stored: str,
) -> None:
    client, conversation_id, store = taken
    await post_agent_text(client, conversation_id)
    await rewrite_message_field(
        store,
        conversation_id,
        "content_enc",
        None,
        remove=as_stored == "missing",
    )
    caplog.clear()

    with caplog.at_level("DEBUG"):
        reads = [
            await client.get(template.format(conversation_id), headers=AUTH)
            for template in READS
        ]
        replay = await post_agent_text(client, conversation_id)
        new = await post_agent_text(
            client, conversation_id, "Nuevo, soy Ana", "cmid-0000002"
        )

    for response in reads:
        assert [m["content"] for m in response.json()["messages"]] == [
            AGENT_TEXT_MASKED
        ]
    assert replay.json()["message"]["content"] == AGENT_TEXT_MASKED
    # Nothing to decrypt is not a failure: no warning, and no attempt to log one.
    assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
    # Old and new messages live side by side.
    assert new.json()["message"]["content"] == "Nuevo, soy Ana"
    shown = (await client.get(READS[1].format(conversation_id))).json()["messages"]
    assert [m["content"] for m in shown] == [AGENT_TEXT_MASKED, "Nuevo, soy Ana"]


async def test_an_old_state_with_no_field_at_all_still_loads(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    """The stored JSON of a deployment that never wrote `content_enc`."""
    app = build_app(redis, FakeTurnHandler(), settings=agent_settings())
    client = make_client(app)
    conversation_id = await open_conversation(client)
    key = f"orch:conv:{conversation_id}"
    payload = json.loads(await redis.get(key))
    payload["messages"] = [
        {
            "role": "agent",
            "content": "Hola, soy [NAME_1].",
            "blocks": [],
            "metadata": {},
            "client_message_id": "cmid-0000001",
            "created_at": "2026-09-28T12:00:00Z",
        }
    ]
    await redis.set(key, json.dumps(payload), keepttl=True)

    for template in READS:
        response = await client.get(template.format(conversation_id), headers=AUTH)

        assert response.status_code == 200
        assert response.json()["messages"][0]["content"] == "Hola, soy [NAME_1]."


async def test_a_text_that_cannot_be_encrypted_is_not_saved_and_not_logged(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, conversation_id, store = taken

    def broken(text: str) -> str:
        raise CryptoError("Text encryption failed")

    monkeypatch.setattr(store.encryptor, "encrypt_text", broken)
    with caplog.at_level("DEBUG"):
        response = await post_agent_text(client, conversation_id)

    # Never stored with only its masked twin: the customer would read a
    # different text from the one the agent sent, and the agent would not know.
    assert response.status_code == 503
    assert response.json() == {"detail": "The message was not saved"}
    assert (await store.get(conversation_id)).messages == []
    assert not any(
        piece in r.getMessage() for r in caplog.records for piece in AGENT_TEXT_PIECES
    )


async def test_no_log_carries_the_text_an_agent_wrote(
    taken: tuple[httpx.AsyncClient, str, SessionStore],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, conversation_id, store = taken
    ciphertexts: list[str] = []

    with caplog.at_level("DEBUG"):
        await post_agent_text(client, conversation_id)
        await post_agent_text(client, conversation_id)  # the replay
        for template in READS:
            await client.get(template.format(conversation_id), headers=AUTH)
        ciphertexts.append(
            (await stored_json(store, conversation_id))["messages"][0]["content_enc"]
        )
        await rewrite_message_field(store, conversation_id, "content_enc", "corrupt")
        for template in READS:
            await client.get(template.format(conversation_id), headers=AUTH)

    logged = "\n".join(
        f"{r.name} {r.getMessage()} {r.exc_text or ''}" for r in caplog.records
    )
    for secret in (*AGENT_TEXT_PIECES, *ciphertexts):
        assert secret not in logged, secret


# ---------------------------------------------------------------- transcript shapes


async def test_the_customer_transcript_shape_before_and_after_a_takeover(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))
    conversation_id = await open_conversation(client)
    customer_url = f"/v1/conversations/{conversation_id}"

    before = (await client.get(customer_url)).json()
    assert before == {
        "conversation_id": conversation_id,
        "language": "es",
        "locale": None,
        "messages": [],
        "takeover": {"active": False, "since": None},
    }

    await take_over(client, conversation_id)
    await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body("Hola, te atiende el equipo de disputas."),
        headers=agent_headers(),
    )
    await client.post(f"{customer_url}/messages", json={"text": "Hola Ana"})
    after = (await client.get(customer_url)).json()

    assert set(after) == {
        "conversation_id",
        "language",
        "locale",
        "messages",
        "takeover",
    }
    assert set(after["takeover"]) == {"active", "since"}
    assert after["takeover"]["active"] is True
    assert after["takeover"]["since"] is not None
    assert [(m["role"], m["content"]) for m in after["messages"]] == [
        ("agent", "Hola, te atiende el equipo de disputas."),
        ("user", "Hola Ana"),
    ]
    for message in after["messages"]:
        assert set(message) == {"role", "content", "blocks", "created_at"}
    # No agent identity and no retry handle anywhere in what a customer reads.
    serialized = json.dumps(after)
    assert ANA not in serialized and "agent_ref" not in serialized
    assert "cmid-0000001" not in serialized and "client_message_id" not in serialized


async def test_the_agent_transcript_shape_names_the_holder(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))
    conversation_id = await open_conversation(client)
    url = f"/v1/agent/conversations/{conversation_id}"

    before = (await client.get(url, headers=AUTH)).json()
    assert before == {
        "conversation_id": conversation_id,
        "language": "es",
        "messages": [],
        "takeover": {"active": False, "since": None, "agent_ref": None},
    }

    await take_over(client, conversation_id)
    await client.post(
        f"{url}/messages",
        json=message_body("Hola, te atiende el equipo de disputas."),
        headers=agent_headers(),
    )
    after = (await client.get(url, headers=AUTH)).json()

    assert set(after["takeover"]) == {"active", "since", "agent_ref"}
    assert after["takeover"]["agent_ref"] == ANA
    assert after["takeover"]["since"] is not None
    assert [(m["role"], m["content"]) for m in after["messages"]] == [
        ("agent", "Hola, te atiende el equipo de disputas.")
    ]
    assert set(after["messages"][0]) == {"role", "content", "blocks", "created_at"}
    assert "client_message_id" not in json.dumps(after)


async def test_the_agent_transcript_of_an_unknown_conversation_is_404(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))

    response = await client.get(
        "/v1/agent/conversations/conv_" + "0" * 32, headers=AUTH
    )

    assert response.status_code == 404


async def test_the_agent_transcript_shows_receipts_and_never_the_llm_history(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    handler = FakeTurnHandler(reply="Recibido")
    client = make_client(build_app(redis, handler, settings=agent_settings()))
    conversation_id = await open_conversation(client)
    await client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": f"Mi cédula es {RAW_DOCUMENT}"},
    )

    body = (
        await client.get(f"/v1/agent/conversations/{conversation_id}", headers=AUTH)
    ).text

    assert RAW_DOCUMENT not in body
    assert "llm_history" not in body and "placeholder_map" not in body
    assert '"receipt"' in body


async def test_the_index_key_is_not_a_conversation_capability(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    """The banking session id alone opens nothing on the customer's routes."""
    client = make_client(build_app(redis, FakeTurnHandler(), settings=agent_settings()))
    await open_conversation(client)

    for path in (
        "/v1/conversations/sess_opaque_0001",
        "/v1/conversations/sess_opaque_0001/inbox",
    ):
        assert (await client.get(path)).status_code == 404


def test_the_app_wires_the_index_prefix_from_settings() -> None:
    settings = agent_settings(redis_edge_session_index_key_prefix="orch:sidx:")
    app = create_app(
        settings=settings,
        banking_client=BankingCoreClient(base_url=BANKING_URL, settings=settings),
        turn_handler=FakeTurnHandler(),
    )

    assert app.state.session_store.session_index_prefix == "orch:sidx:"
