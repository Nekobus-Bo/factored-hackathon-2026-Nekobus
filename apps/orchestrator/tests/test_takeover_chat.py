"""The customer's chat during a human takeover, and the engine's refusal.

Once an agent holds a conversation the assistant is out of it for good: the
customer's messages are stored masked and wait for the agent. The fakes below
fail the test if anything reaches them, so "never" is proved, not assumed.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fakeredis
import httpx
import pytest
import respx
from contracts import ToolCall, ToolResult
from fastapi import FastAPI
from orchestrator.chat.engine_handler import EngineTurnHandler
from orchestrator.config import Settings
from orchestrator.conversation import (
    ConversationContext,
    TakeoverActiveError,
    TurnEngine,
)
from orchestrator.encoder_client import EncoderClient
from orchestrator.llm.provider import LLMResponse
from orchestrator.main import create_app
from orchestrator.session.crypto import PlaceholderEncryptor
from orchestrator.session.models import ConversationState, Message, Takeover
from orchestrator.session.store import SessionStore
from orchestrator.tools_client import BankingCoreClient
from pydantic import ValidationError

from .fake_handler import RECEIPT_BLOCK, FakeTurnHandler
from .fake_llm import ScriptedLLM, Step
from .test_agent_api import (
    AGENT_TEXT,
    AGENT_TEXT_MASKED,
    AGENT_TEXT_PIECES,
    ANA,
    AUTH,
    HANDOFF,
    RAW_DOCUMENT,
    agent_headers,
    agent_settings,
    message_body,
    open_conversation,
    post_agent_text,
    take_over,
)
from .test_chat_api import BANKING_URL, build_app

MakeClient = Callable[[FastAPI], httpx.AsyncClient]
SESSION_ID = "sess_opaque_0001"
CID = "client-msg-0001"


class NeverLLM:
    """Fails the test if the conversation ever reaches the model."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        raise AssertionError("the LLM was called on a taken-over conversation")


class NeverBanking:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(self, session_id: str, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
        raise AssertionError("a banking-core tool ran on a taken-over conversation")


class NeverEncoder:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("the encoder saw text of a taken-over conversation")


class Never:
    """One of each fake, wired into a real engine."""

    def __init__(self) -> None:
        self.llm = NeverLLM()
        self.banking = NeverBanking()
        self.encoder = NeverEncoder()
        self.engine = TurnEngine(
            llm=self.llm, banking=self.banking, encoder=self.encoder
        )

    def untouched(self) -> bool:
        return (self.llm.calls, self.banking.calls, self.encoder.calls) == (0, 0, 0)


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis()


@pytest.fixture
def banking() -> Any:
    """banking-core answers only POST /v1/sessions; any other request is an error."""
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BANKING_URL}/v1/sessions").mock(
            return_value=httpx.Response(201, json={"session_id": SESSION_ID})
        )
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


def new_store(redis: fakeredis.FakeAsyncRedis) -> SessionStore:
    return SessionStore(
        redis=redis,
        encryptor=PlaceholderEncryptor("test-secret"),
        ttl_seconds=3600,
        lock_timeout_seconds=30,
    )


def app_with_engine(
    redis: fakeredis.FakeAsyncRedis, never: Never, **settings: Any
) -> FastAPI:
    """The real app and the real engine handler over fakes that must stay unused."""
    cfg = agent_settings(**settings)
    return create_app(
        settings=cfg,
        session_store=new_store(redis),
        banking_client=BankingCoreClient(base_url=BANKING_URL, settings=cfg),
        turn_handler=EngineTurnHandler(never.engine),
    )


def messages_url(conversation_id: str) -> str:
    return f"/v1/conversations/{conversation_id}/messages"


def banking_requests(router: Any) -> list[str]:
    return [f"{c.request.method} {c.request.url.path}" for c in router.calls]


# ------------------------------------------- the customer's messages, during a takeover


async def test_a_customer_message_during_a_takeover_reaches_no_llm_encoder_or_tool(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    never = Never()
    client = make_client(app_with_engine(redis, never))
    conversation_id = await open_conversation(client)
    assert (await take_over(client, conversation_id)).status_code == 200

    response = await client.post(
        messages_url(conversation_id),
        json={"text": "Necesito ayuda con un cargo que no reconozco", "lang": "es"},
    )

    assert response.status_code == 200
    assert response.json() == {"conversation_id": conversation_id, "blocks": []}
    assert never.untouched()
    # Only the session opened at creation ever went to banking-core.
    assert banking_requests(banking) == ["POST /v1/sessions"]


async def test_a_conversation_turn_before_the_takeover_still_runs_and_none_after(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    llm = ScriptedLLM([Step(content="Hola, ¿en qué te ayudo?")])
    never = Never()
    engine = TurnEngine(llm=llm, banking=never.banking, encoder=None)
    cfg = agent_settings()
    client = make_client(
        create_app(
            settings=cfg,
            session_store=new_store(redis),
            banking_client=BankingCoreClient(base_url=BANKING_URL, settings=cfg),
            turn_handler=EngineTurnHandler(engine),
        )
    )
    conversation_id = await open_conversation(client)

    first = await client.post(messages_url(conversation_id), json={"text": "Hola"})
    assert first.json()["blocks"] == [
        {"type": "text", "text": "Hola, ¿en qué te ayudo?"}
    ]
    assert len(llm.calls) == 1

    await take_over(client, conversation_id)
    for text in ("¿Sigues ahí?", "Hola?", "Necesito un agente"):
        response = await client.post(messages_url(conversation_id), json={"text": text})
        assert response.status_code == 200
        assert response.json()["blocks"] == []

    assert len(llm.calls) == 1  # ScriptedLLM would raise on a second call anyway
    assert never.banking.calls == 0
    transcript = (await client.get(f"/v1/conversations/{conversation_id}")).json()
    assert [(m["role"], m["content"]) for m in transcript["messages"]] == [
        ("user", "Hola"),
        ("assistant", "Hola, ¿en qué te ayudo?"),
        ("user", "¿Sigues ahí?"),
        ("user", "Hola?"),
        ("user", "Necesito un agente"),
    ]


async def test_the_handler_is_never_called_during_a_takeover(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    handler = FakeTurnHandler()
    client = make_client(build_app(redis, handler, settings=agent_settings()))
    conversation_id = await open_conversation(client)
    await client.post(messages_url(conversation_id), json={"text": "antes"})
    await take_over(client, conversation_id)

    for i in range(3):
        await client.post(
            messages_url(conversation_id),
            json={"text": f"después {i}", "client_message_id": f"client-msg-{i:04d}"},
        )

    assert [text for _, text in handler.calls] == ["antes"]


async def test_the_customer_message_is_stored_masked_and_nothing_else(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    never = Never()
    app = app_with_engine(redis, never)
    client = make_client(app)
    conversation_id = await open_conversation(client)
    await take_over(client, conversation_id)
    text = (
        f"Mi cédula es {RAW_DOCUMENT}, mi correo carla@example.com "
        "y mi tarjeta es 4111 1111 1111 1111"
    )

    response = await client.post(messages_url(conversation_id), json={"text": text})

    assert response.status_code == 200
    state = await app.state.session_store.get(conversation_id)
    assert [(m.role.value, m.content) for m in state.messages] == [
        (
            "user",
            "Mi cédula es [DOC_1], mi correo [EMAIL_1] y mi tarjeta es [CARD_1]",
        )
    ]
    assert state.llm_history == []
    raw = await redis.get(f"orch:conv:{conversation_id}")
    for secret in (RAW_DOCUMENT, "carla@example.com", "4111 1111"):
        assert secret.encode() not in raw
    for path in (
        f"/v1/conversations/{conversation_id}",
        f"/v1/agent/conversations/{conversation_id}",
    ):
        body = (await client.get(path, headers=AUTH)).text
        assert RAW_DOCUMENT not in body and "carla@example.com" not in body


async def test_a_retried_customer_message_is_stored_once(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    never = Never()
    app = app_with_engine(redis, never)
    client = make_client(app)
    conversation_id = await open_conversation(client)
    await take_over(client, conversation_id)
    body = {"text": "Necesito ayuda", "client_message_id": CID}

    first = await client.post(messages_url(conversation_id), json=body)
    await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body("Ya te leo."),
        headers=agent_headers(),
    )
    retry = await client.post(messages_url(conversation_id), json=body)
    next_message = await client.post(
        messages_url(conversation_id),
        json={"text": "Otra cosa", "client_message_id": "client-msg-0002"},
    )

    assert first.status_code == retry.status_code == next_message.status_code == 200
    assert (
        first.json()
        == retry.json()
        == {
            "conversation_id": conversation_id,
            "blocks": [],
        }
    )
    state = await app.state.session_store.get(conversation_id)
    assert [(m.role.value, m.content) for m in state.messages] == [
        ("user", "Necesito ayuda"),
        ("agent", "Ya te leo."),
        ("user", "Otra cosa"),
    ]
    assert never.untouched()


async def test_a_message_without_an_id_is_not_deduplicated(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = app_with_engine(redis, Never())
    client = make_client(app)
    conversation_id = await open_conversation(client)
    await take_over(client, conversation_id)

    for _ in range(2):
        await client.post(messages_url(conversation_id), json={"text": "hola"})

    state = await app.state.session_store.get(conversation_id)
    assert [m.content for m in state.messages] == ["hola", "hola"]
    assert state.last_turn is None


async def test_a_retry_of_the_turn_that_completed_before_the_takeover_gets_its_outcome(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    handler = FakeTurnHandler(reply="Listo")
    app = build_app(redis, handler, settings=agent_settings())
    client = make_client(app)
    conversation_id = await open_conversation(client)
    body = {"text": "bloquea mi tarjeta", "client_message_id": CID}
    first = await client.post(messages_url(conversation_id), json=body)
    await take_over(client, conversation_id)

    retry = await client.post(messages_url(conversation_id), json=body)

    assert retry.json() == first.json()
    assert retry.json()["blocks"][-1] == RECEIPT_BLOCK
    assert len(handler.calls) == 1
    state = await app.state.session_store.get(conversation_id)
    assert [m.role.value for m in state.messages] == ["user", "assistant"]


async def test_the_language_can_still_change_during_a_takeover(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = app_with_engine(redis, Never())
    client = make_client(app)
    conversation_id = await open_conversation(client)
    await take_over(client, conversation_id)

    await client.post(
        messages_url(conversation_id), json={"text": "hello", "lang": "en"}
    )

    assert (await app.state.session_store.get(conversation_id)).language == "en"


async def test_a_customer_message_waits_for_the_agent_api_instead_of_failing(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = app_with_engine(redis, Never(), agent_lock_wait_seconds=5)
    store: SessionStore = app.state.session_store
    client = make_client(app)
    conversation_id = await open_conversation(client)
    await take_over(client, conversation_id)
    token = await store.acquire_turn_lock(conversation_id)
    assert token is not None

    pending = asyncio.create_task(
        client.post(messages_url(conversation_id), json={"text": "hola"})
    )
    await asyncio.sleep(0.2)
    assert not pending.done()
    await store.release_turn_lock(conversation_id, token)
    response = await pending

    assert response.status_code == 200


async def test_without_a_takeover_a_turn_in_flight_still_answers_409(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = app_with_engine(redis, Never(), agent_lock_wait_seconds=5)
    store: SessionStore = app.state.session_store
    client = make_client(app)
    conversation_id = await open_conversation(client)
    assert await store.acquire_turn_lock(conversation_id) is not None

    response = await asyncio.wait_for(
        client.post(messages_url(conversation_id), json={"text": "hola"}), timeout=1
    )

    assert response.status_code == 409


async def test_a_message_stays_stored_when_it_lands_during_the_takeover_race(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    """A turn already past the takeover check cannot be overtaken by it.

    The takeover waits for the lock, so the message and the takeover are
    serialized: whichever comes second sees the other.
    """
    gate = asyncio.Event()
    handler = FakeTurnHandler(gate=gate)
    app = build_app(redis, handler, settings=agent_settings(agent_lock_wait_seconds=5))
    client = make_client(app)
    conversation_id = await open_conversation(client)
    turn = asyncio.create_task(
        client.post(messages_url(conversation_id), json={"text": "primero"})
    )
    await asyncio.wait_for(handler.started.wait(), timeout=2)
    takeover = asyncio.create_task(take_over(client, conversation_id))
    await asyncio.sleep(0.1)
    gate.set()
    await asyncio.gather(turn, takeover)

    after = await client.post(messages_url(conversation_id), json={"text": "segundo"})

    assert after.json()["blocks"] == []
    assert [text for _, text in handler.calls] == ["primero"]
    state = await app.state.session_store.get(conversation_id)
    assert [(m.role.value, m.content) for m in state.messages] == [
        ("user", "primero"),
        ("assistant", "Recibido: primero"),
        ("user", "segundo"),
    ]


# ---------------------------------------------------------------- the eval hook


async def test_the_eval_hook_shows_no_provider_data_for_a_takeover_message(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = app_with_engine(redis, Never(), eval_expose_turn=True)
    client = make_client(app)
    conversation_id = await open_conversation(client)
    await take_over(client, conversation_id)

    response = await client.post(messages_url(conversation_id), json={"text": "hola"})

    assert response.status_code == 200
    body = response.json()
    assert body["blocks"] == []
    assert body["eval"] == {
        "masked_outbound": [],
        "recording_keys": [],
        "tokens": 0,
        "cost_usd": 0.0,
        "decisions": [],
        "effects": [],
    }


async def test_the_eval_key_is_absent_when_the_hook_is_off(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    client = make_client(app_with_engine(redis, Never()))
    conversation_id = await open_conversation(client)
    await take_over(client, conversation_id)

    response = await client.post(messages_url(conversation_id), json={"text": "hola"})

    assert "eval" not in response.json()


# ------------------------------------------------------- codes typed to the agent


def pending_otp_history() -> list[dict[str, Any]]:
    """An OTP challenge the assistant opened and nothing has closed."""
    result = {"tool": "otp.send", "status": "ok", "data": {"sent": True}}
    return [{"role": "tool", "tool_call_id": "call_1", "content": json.dumps(result)}]


async def test_a_code_typed_into_a_pending_challenge_is_masked_after_the_takeover(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    app = app_with_engine(redis, Never())
    store: SessionStore = app.state.session_store
    client = make_client(app)
    conversation_id = await open_conversation(client)
    state = await store.get(conversation_id)
    assert state is not None
    state.llm_history = pending_otp_history()
    await store.save(state)
    await take_over(client, conversation_id)

    await client.post(messages_url(conversation_id), json={"text": "482913"})
    await client.post(
        messages_url(conversation_id), json={"text": "es 482 913 otra vez"}
    )

    stored = await store.get(conversation_id)
    assert stored is not None
    assert [m.content for m in stored.messages] == ["[OTP_1]", "es [OTP_2] otra vez"]
    assert b"482913" not in await redis.get(f"orch:conv:{conversation_id}")
    for path in (
        f"/v1/conversations/{conversation_id}",
        f"/v1/agent/conversations/{conversation_id}",
    ):
        shown = (await client.get(path, headers=AUTH)).json()["messages"]
        assert [m["content"] for m in shown] == ["[OTP_1]", "es [OTP_2] otra vez"]


async def test_plain_numbers_are_kept_when_no_challenge_is_pending(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    """An agent working a dispute needs the amounts the customer states."""
    app = app_with_engine(redis, Never())
    client = make_client(app)
    conversation_id = await open_conversation(client)
    await take_over(client, conversation_id)

    await client.post(
        messages_url(conversation_id), json={"text": "Me cobraron 25000 pesos"}
    )

    stored = await app.state.session_store.get(conversation_id)
    assert stored is not None
    assert stored.messages[0].content == "Me cobraron 25000 pesos"


# --------------------------------------- the engine refuses, whoever calls it


def taken_over_state() -> ConversationState:
    now = datetime.now(UTC)
    return ConversationState(
        banking_session_id=SESSION_ID,
        llm_history=[
            {"role": "user", "content": "Perdí mi tarjeta, mi cédula es [DOC_1]"},
            {"role": "assistant", "content": "Te ayudo."},
        ],
        placeholder_map={"[DOC_1]": RAW_DOCUMENT},
        messages=[Message(role="user", content="Perdí mi tarjeta")],
        takeover=Takeover(active=True, since=now, agent_ref=ANA),
    )


async def test_the_engine_refuses_a_turn_on_a_taken_over_context() -> None:
    never = Never()
    context = ConversationContext(
        session_id=SESSION_ID,
        history=[{"role": "user", "content": "antes"}],
        placeholder_map={"[DOC_1]": RAW_DOCUMENT},
        human_takeover=True,
    )
    before = context.model_copy(deep=True)

    with pytest.raises(TakeoverActiveError):
        await never.engine.run_turn(context, "Hola de nuevo", turn_id="t1")

    assert never.untouched()
    assert context == before


async def test_the_engine_handler_refuses_a_taken_over_conversation() -> None:
    never = Never()
    handler = EngineTurnHandler(never.engine)
    state = taken_over_state()
    before = state.model_copy(deep=True)

    with pytest.raises(TakeoverActiveError):
        await handler.handle_turn(state, "¿Me ayudas?", turn_id="t1")

    assert never.untouched()
    assert state == before  # no history, no map, no message touched


async def test_no_model_is_offered_the_history_of_a_taken_over_conversation() -> None:
    """Even a model that would answer is not asked: the door is shut before it."""
    llm = ScriptedLLM([Step(content="respuesta")], repeat_last=True)
    never = Never()
    engine = TurnEngine(
        llm=llm,
        banking=never.banking,
        encoder=EncoderClient(
            base_url="http://encoder.test",
            timeout=1.0,
            settings=Settings(_env_file=None),
        ),
    )
    handler = EngineTurnHandler(engine)

    with respx.mock() as router:  # any request, even to the encoder, would raise
        with pytest.raises(TakeoverActiveError):
            await handler.handle_turn(taken_over_state(), "hola")
        assert router.calls.call_count == 0

    assert llm.calls == []
    assert llm.payload_dump() == "[]"


async def test_the_flag_is_set_from_the_conversation_by_the_handler() -> None:
    """A conversation with no takeover runs; the same one taken over does not."""
    llm = ScriptedLLM([Step(content="Hola")])
    engine = TurnEngine(llm=llm, banking=NeverBanking(), encoder=None)
    handler = EngineTurnHandler(engine)
    state = ConversationState(banking_session_id=SESSION_ID)

    outcome = await handler.handle_turn(state, "hola")
    assert outcome.blocks == [{"type": "text", "text": "Hola"}]
    assert len(llm.calls) == 1

    state.takeover = Takeover(active=True, since=datetime.now(UTC), agent_ref=ANA)
    with pytest.raises(TakeoverActiveError):
        await handler.handle_turn(state, "otra vez")
    assert len(llm.calls) == 1


def test_a_context_is_open_unless_the_conversation_says_otherwise() -> None:
    assert ConversationContext(session_id=SESSION_ID).human_takeover is False


# ------------------------------- the agent's text as written never reaches the LLM


async def test_the_engine_refuses_a_conversation_that_holds_agent_text() -> None:
    """The guard is the door: agent text, masked or as written, changes nothing."""
    llm = ScriptedLLM([Step(content="respuesta")], repeat_last=True)
    engine = TurnEngine(llm=llm, banking=NeverBanking(), encoder=None)
    encryptor = PlaceholderEncryptor("test-secret")
    state = taken_over_state()
    state.messages.append(
        Message(
            role="agent",
            content=AGENT_TEXT_MASKED,
            content_enc=encryptor.encrypt_text(AGENT_TEXT),
        )
    )

    with pytest.raises(TakeoverActiveError):
        await EngineTurnHandler(engine).handle_turn(state, "hola")

    assert llm.calls == []


async def test_a_takeover_cleared_by_hand_still_sends_the_llm_no_agent_text(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    """Belt and braces: the history the engine builds never holds agent messages.

    The takeover guard already keeps the model out of a taken-over conversation.
    Suppose it were cleared by hand after an agent wrote: the engine would run
    again, and what it builds from the conversation is `llm_history`, which agent
    messages never enter. Neither the text as written, nor its ciphertext, nor
    even its masked twin reaches the provider.
    """
    llm = ScriptedLLM([Step(content="Hola, ¿en qué te ayudo?"), Step(content="Sigo")])
    engine = TurnEngine(llm=llm, banking=NeverBanking(), encoder=None)
    cfg = agent_settings()
    store = new_store(redis)
    client = make_client(
        create_app(
            settings=cfg,
            session_store=store,
            banking_client=BankingCoreClient(base_url=BANKING_URL, settings=cfg),
            turn_handler=EngineTurnHandler(engine),
        )
    )
    conversation_id = await open_conversation(client)
    await client.post(messages_url(conversation_id), json={"text": "Hola"})
    await take_over(client, conversation_id)
    assert (await post_agent_text(client, conversation_id)).status_code == 200
    await client.post(messages_url(conversation_id), json={"text": "Gracias"})
    assert len(llm.calls) == 1

    state = await store.get(conversation_id)
    assert state is not None and state.takeover.active
    agent_message = next(m for m in state.messages if m.role.value == "agent")
    assert agent_message.content == AGENT_TEXT_MASKED
    assert agent_message.content_enc is not None
    ciphertext = agent_message.content_enc
    history_before = state.llm_history
    state.takeover = Takeover()  # the hand-edit
    await store.save(state)

    response = await client.post(
        messages_url(conversation_id), json={"text": "¿Sigues ahí?"}
    )

    assert response.status_code == 200
    assert response.json()["blocks"] == [{"type": "text", "text": "Sigo"}]
    assert len(llm.calls) == 2
    sent = llm.calls[1]["messages"]
    assert [(m["role"], m["content"]) for m in sent[1:]] == [
        ("user", "Hola"),
        ("assistant", "Hola, ¿en qué te ayudo?"),
        ("user", "¿Sigues ahí?"),
    ]
    payload = llm.payload_dump()
    for secret in (*AGENT_TEXT_PIECES, ciphertext, "content_enc", AGENT_TEXT_MASKED):
        assert secret not in payload, secret
    # What the engine left behind is the same: no agent text in the history.
    after = await store.get(conversation_id)
    assert after is not None
    assert after.llm_history[: len(history_before)] == history_before
    assert [m["role"] for m in after.llm_history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert not any(
        piece in json.dumps(after.llm_history) for piece in AGENT_TEXT_PIECES
    )


def test_only_the_transcript_and_the_agent_route_touch_the_text_as_written() -> None:
    """A structural guard: nothing on the LLM side can read `content_enc`.

    The engine, the provider, the encoder client, the tools client and the turn
    handlers never name it; a new reader has to show up in this list, and so in
    review.
    """
    import orchestrator

    root = Path(orchestrator.__file__).parent
    names = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "content_enc" in path.read_text()
    )

    assert names == [
        "agent/routes.py",  # writes it, and reads it back to answer
        "chat/transcript.py",  # decrypts it for a reader
        "session/models.py",  # declares it
    ]
    # And the engine's only view of a conversation has no room for its messages.
    assert "messages" not in ConversationContext.model_fields


# ------------------------------------------------------------- the takeover state


def test_an_active_takeover_names_its_holder_and_time() -> None:
    now = datetime.now(UTC)

    assert Takeover().model_dump() == {
        "active": False,
        "since": None,
        "agent_ref": None,
    }
    assert Takeover(active=True, since=now, agent_ref=ANA).active is True
    # Released by its agent (ADR-0018): still active, nobody holds it.
    assert Takeover(active=True, since=now).agent_ref is None
    with pytest.raises(ValidationError):
        Takeover(active=True, since=now, agent_ref="")
    with pytest.raises(ValidationError):
        Takeover(active=True, agent_ref=ANA)
    with pytest.raises(ValidationError):
        Takeover(active=False, agent_ref=ANA)


async def test_takeover_state_survives_the_store(
    redis: fakeredis.FakeAsyncRedis,
) -> None:
    store = new_store(redis)
    state = taken_over_state()
    await store.save(state)

    loaded = await store.get(state.conversation_id)

    assert loaded is not None
    assert loaded.takeover == state.takeover
    assert loaded.model_dump() == state.model_dump()


async def test_a_conversation_stored_before_takeovers_existed_loads_as_open(
    redis: fakeredis.FakeAsyncRedis,
) -> None:
    store = new_store(redis)
    state = ConversationState(banking_session_id=SESSION_ID)
    await store.save(state)
    raw = json.loads(await redis.get(f"orch:conv:{state.conversation_id}"))
    del raw["takeover"]
    await redis.set(f"orch:conv:{state.conversation_id}", json.dumps(raw))

    loaded = await store.get(state.conversation_id)

    assert loaded is not None
    assert loaded.takeover.active is False


async def test_the_taken_over_flow_end_to_end(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: MakeClient
) -> None:
    """Customer, takeover, agent reply, customer reply: what each side reads."""
    never = Never()
    client = make_client(app_with_engine(redis, never))
    conversation_id = await open_conversation(client)
    takeover = await client.post(
        f"/v1/agent/conversations/{conversation_id}/takeover",
        json={"agent_ref": ANA, "handoff_ref": HANDOFF},
        headers=AUTH,
    )
    assert takeover.status_code == 200

    await client.post(messages_url(conversation_id), json={"text": "¿Hay novedades?"})
    reply = await client.post(
        f"/v1/agent/conversations/{conversation_id}/messages",
        json=message_body("Estoy revisando el cargo."),
        headers=agent_headers(),
    )
    await client.post(messages_url(conversation_id), json={"text": "Gracias"})

    assert reply.status_code == 200
    expected = [
        ("user", "¿Hay novedades?"),
        ("agent", "Estoy revisando el cargo."),
        ("user", "Gracias"),
    ]
    customer = (await client.get(f"/v1/conversations/{conversation_id}")).json()
    agent = (
        await client.get(f"/v1/agent/conversations/{conversation_id}", headers=AUTH)
    ).json()
    assert [(m["role"], m["content"]) for m in customer["messages"]] == expected
    assert [(m["role"], m["content"]) for m in agent["messages"]] == expected
    assert customer["takeover"] == {"active": True, "since": agent["takeover"]["since"]}
    assert never.untouched()
    assert banking_requests(banking) == ["POST /v1/sessions"]
