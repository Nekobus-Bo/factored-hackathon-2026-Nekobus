"""Chat API + redis-edge session store: fakeredis, fake handler, respx."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import httpx
import pytest
import respx
from fastapi import FastAPI
from orchestrator.chat.engine_handler import EngineTurnHandler
from orchestrator.chat.handler import TurnHandler, TurnOutcome, derive_turn_id
from orchestrator.config import Settings
from orchestrator.conversation import ConversationContext, TurnEngine
from orchestrator.main import create_app
from orchestrator.session.crypto import PlaceholderEncryptor
from orchestrator.session.models import ConversationState
from orchestrator.session.store import SessionStore
from orchestrator.tools_client import BankingCoreClient

from .fake_handler import RECEIPT_BLOCK, FakeTurnHandler
from .fake_llm import ScriptedLLM, Step, tool_call
from .test_conversation_engine import FakeBankingCore

BANKING_URL = "http://banking-core.test"
RAW_DOCUMENT = "1020304050"
RAW_NAME = "Carlos"


def build_app(
    redis: fakeredis.FakeAsyncRedis,
    handler: TurnHandler | None,
    ttl_seconds: int = 3600,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings()
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


def _litellm_response(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> MagicMock:
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls or []
    response.choices = [choice]
    response.usage.model_dump.return_value = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    return response


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
    assert body == {
        "conversation_id": conversation_id,
        "language": "pt",
        "locale": None,
    }
    assert conversation_id.startswith("conv_")

    user_text = f"Me llamo {RAW_NAME}, mi cédula es {RAW_DOCUMENT}"
    sent = await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": user_text}
    )
    assert sent.status_code == 200
    assert "eval" not in sent.json()
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


async def test_default_replay_handler_returns_replay_miss(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: Any,
    tmp_path: Path,
) -> None:
    settings = Settings(
        replay_dir=str(tmp_path),
        encoder_enabled=False,
    )
    client = make_client(build_app(redis, None, settings=settings))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]

    response = await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": "hola"}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "replay_miss"
    assert (await client.get(f"/v1/conversations/{conversation_id}")).json()[
        "messages"
    ] == []


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


async def test_invalid_message_block_is_not_persisted(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: Any,
) -> None:
    class InvalidBlockHandler:
        async def handle_turn(
            self,
            conversation: ConversationState,
            user_text: str,
            turn_id: str | None = None,
        ) -> TurnOutcome:
            return TurnOutcome(blocks=[{"type": "handoff"}], metadata={})

    client = make_client(build_app(redis, InvalidBlockHandler()))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]

    response = await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": "hola"}
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Turn output violates the message block contract"
    )
    assert (await client.get(f"/v1/conversations/{conversation_id}")).json()[
        "messages"
    ] == []


@pytest.mark.parametrize(
    "app_env",
    ["production", "Production", "PRODUCTION", " production ", "\tProduction\n"],
)
def test_startup_rejects_eval_hook_in_production(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("EVAL_EXPOSE_TURN", "true")

    with pytest.raises(ValueError, match="EVAL_EXPOSE_TURN"):
        create_app(settings=Settings(_env_file=None))


@pytest.mark.parametrize("app_env", ["development", "staging", "production-like"])
def test_startup_allows_eval_hook_outside_production(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("EVAL_EXPOSE_TURN", "true")

    app = create_app(settings=Settings(_env_file=None))

    assert app.state.eval_expose_turn is True


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


@pytest.mark.parametrize("lang", ["es", "pt", "en"])
async def test_replay_turns_work_through_chat_api_without_provider_pii(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: Any,
    tmp_path: Path,
    lang: str,
) -> None:
    replay_dir = tmp_path / "replay"
    record_settings = Settings(
        _env_file=None,
        llm_mode="live",
        llm_model="test-model",
        replay_dir=str(replay_dir),
        record=True,
        encoder_enabled=False,
        session_secret="test-secret",
    )
    fake_banking = FakeBankingCore()
    banking.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=fake_banking)

    user_text = {
        "es": "Perdí mi tarjeta; documento 1020304050",
        "pt": "Perdi meu cartão; documento 1020304050",
        "en": "I lost my card; document 1020304050",
    }[lang]
    otp_text = "482 913"
    script = [
        _litellm_response(
            tool_calls=[
                tool_call(
                    "call_match",
                    "customer_match",
                    {
                        "document_type": "NATIONAL_ID",
                        "document_number": "[DOC_1]",
                    },
                )
            ]
        ),
        _litellm_response(tool_calls=[tool_call("call_send", "otp_send", {})]),
        _litellm_response(content="I sent a code; please share it."),
        _litellm_response(
            tool_calls=[tool_call("call_verify", "otp_verify", {"code": "[OTP_1]"})]
        ),
        _litellm_response(tool_calls=[tool_call("call_list", "card_list", {})]),
        _litellm_response(
            tool_calls=[
                tool_call(
                    "call_block",
                    "card_block",
                    {"card_ref": "card_ab12cd34", "reason": "LOST"},
                )
            ]
        ),
        _litellm_response(
            tool_calls=[
                tool_call(
                    "call_handoff",
                    "handoff_create",
                    {
                        "reason": "CUSTOMER_REQUEST",
                        "summary": "Model request for a dispute review.",
                        "priority": "LOW",
                        "department": "DISPUTES",
                    },
                )
            ]
        ),
        _litellm_response(content=json.dumps({"blocks": [{"type": "handoff"}]})),
    ]
    record_engine = TurnEngine.from_settings(
        record_settings,
        banking=BankingCoreClient(base_url=BANKING_URL, settings=record_settings),
        collect_eval=True,
    )
    record_context = ConversationContext(session_id="sess_opaque_0001", language=lang)
    with (
        patch("litellm.acompletion", new_callable=AsyncMock) as completion,
        patch("litellm.completion_cost", return_value=0.0001),
    ):
        completion.side_effect = script
        await record_engine.run_turn(
            record_context, user_text, lang=lang, turn_id="seed-turn-1"
        )
        await record_engine.run_turn(
            record_context, otp_text, lang=lang, turn_id="seed-turn-2"
        )

    assert completion.call_count == 8
    provider_payloads = json.dumps(
        [call.kwargs["messages"] for call in completion.call_args_list],
        ensure_ascii=False,
    )
    for sensitive_value in (RAW_DOCUMENT, otp_text, "482913"):
        assert sensitive_value not in provider_payloads

    recordings = list(replay_dir.glob("*.json"))
    assert len(recordings) == 8
    for recording in recordings:
        contents = recording.read_text(encoding="utf-8")
        for sensitive_value in (RAW_DOCUMENT, otp_text, "482913"):
            assert sensitive_value not in contents
    fake_banking.requests.clear()

    api_settings = Settings(
        _env_file=None,
        llm_mode="replay",
        llm_model="test-model",
        replay_dir=str(replay_dir),
        encoder_enabled=False,
        eval_expose_turn=True,
        session_secret="test-secret",
    )
    client = make_client(build_app(redis, None, settings=api_settings))
    with patch("litellm.acompletion", new_callable=AsyncMock) as network_call:
        network_call.side_effect = AssertionError("replay must not call a provider")
        created = await client.post("/v1/conversations", json={"lang": lang})
        assert created.status_code == 201
        conversation_id = created.json()["conversation_id"]

        first = await client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json={"text": user_text},
        )
        second = await client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json={"text": otp_text},
        )

    assert network_call.call_count == 0
    assert first.status_code == second.status_code == 200
    for response, expected_calls in ((first, 3), (second, 5)):
        evaluation = response.json()["eval"]
        assert set(evaluation) == {
            "masked_outbound",
            "recording_keys",
            "tokens",
            "cost_usd",
            "decisions",
            "effects",
        }
        # The shipped effects file is loaded, the encoder is off in this test: every
        # decision point is unavailable, so nothing is applied, not even by the two
        # in enforce (ADR-0014, amendment 2026-10-01): no hint, the LLM answers.
        assert [d["dp_id"] for d in evaluation["decisions"]] == [
            "turn_intent",
            "confirm_gate",
            "block_reason",
            "handoff_route",
            "smalltalk_route",
            "intent_hint",
            "clarify_route",
        ]
        assert {d["dp_id"]: d["mode"] for d in evaluation["decisions"]} == {
            "turn_intent": "shadow",
            "confirm_gate": "shadow",
            "block_reason": "shadow",
            "handoff_route": "shadow",
            "smalltalk_route": "shadow",
            "intent_hint": "enforce",
            "clarify_route": "enforce",
        }
        assert {d["outcome"] for d in evaluation["decisions"]} == {"unavailable"}
        assert not any(e["applied"] for e in evaluation["effects"])
        assert len(evaluation["masked_outbound"]) == expected_calls
        assert len(evaluation["recording_keys"]) == expected_calls
        assert evaluation["tokens"] == expected_calls * 15
        assert evaluation["cost_usd"] == pytest.approx(expected_calls * 0.0001)
        outbound = json.dumps(evaluation["masked_outbound"], ensure_ascii=False)
        for sensitive_value in (RAW_DOCUMENT, otp_text, "482913"):
            assert sensitive_value not in outbound

    blocks = second.json()["blocks"]
    assert [block["type"] for block in blocks] == [
        "receipt",
        "receipt",
        "handoff",
    ]
    assert [
        block["receipt"]["action"] for block in blocks if block["type"] == "receipt"
    ] == ["otp.verify", "card.block"]
    handoff = blocks[-1]
    assert handoff["handoff_id"] == "hnd_abcd1234"
    assert handoff["status"] == "QUEUED"
    assert handoff["department"] == "DISPUTES"
    assert handoff["priority"] == "HIGH"
    assert handoff["queue_position"] == 4
    assert handoff["receipt"]["action"] == "handoff.create"
    assert handoff["summary"] == {
        "verified_facts": {
            "verification_state": "VERIFIED",
            "customer_identified": True,
            "policy_flags": [],
        },
        "actions_taken": [],
        "verification_method": "document_match_and_otp",
        "open_questions": [
            {
                "source": "model_unverified",
                "text": "Server-stored handoff question.",
            }
        ],
    }
    assert [request["body"]["tool"] for request in fake_banking.requests] == [
        "customer.match",
        "otp.send",
        "otp.verify",
        "card.list",
        "card.block",
        "handoff.create",
    ]
    assert {request["session"] for request in fake_banking.requests} == {
        "sess_opaque_0001"
    }

    for response in (created, first, second):
        for internal in (
            "banking_session_id",
            "placeholder_map",
            "sess_opaque_0001",
        ):
            assert internal not in response.text
    transcript = await client.get(f"/v1/conversations/{conversation_id}")
    assert transcript.status_code == 200
    for sensitive_value in (RAW_DOCUMENT, otp_text, "482913"):
        assert sensitive_value not in transcript.text


async def test_handoff_block_pii_is_masked_only_in_persisted_transcript(
    redis: fakeredis.FakeAsyncRedis,
    banking: Any,
    make_client: Any,
) -> None:
    class HandoffTurnHandler:
        async def handle_turn(
            self,
            conversation: ConversationState,
            user_text: str,
            turn_id: str | None = None,
        ) -> TurnOutcome:
            conversation.placeholder_map["[DOC_1]"] = RAW_DOCUMENT
            return TurnOutcome(
                blocks=[
                    {
                        "type": "handoff",
                        "handoff_id": "hnd_abcd1234",
                        "status": "QUEUED",
                        "department": "DISPUTES",
                        "priority": "HIGH",
                        "queue_position": 4,
                        "summary": {
                            "verified_facts": {
                                "verification_state": "VERIFIED",
                                "customer_identified": True,
                                "policy_flags": [],
                            },
                            "actions_taken": [],
                            "verification_method": "document_match_and_otp",
                            "open_questions": [
                                {
                                    "source": "model_unverified",
                                    "text": f"Document {RAW_DOCUMENT} needs review.",
                                }
                            ],
                        },
                        "receipt": {
                            "action": "handoff.create",
                            "target_masked": "hnd_abcd1234",
                            "state_before": "NONE",
                            "state_after": "QUEUED",
                            "verified_at": "2026-09-27T12:00:00Z",
                            "audit_id": "aud_0001abcd",
                        },
                    },
                    RECEIPT_BLOCK,
                ],
                metadata={},
            )

    client = make_client(build_app(redis, HandoffTurnHandler()))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]

    response = await client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": "Please escalate this issue."},
    )

    assert response.status_code == 200
    response_blocks = response.json()["blocks"]
    assert RAW_DOCUMENT in response_blocks[0]["summary"]["open_questions"][0]["text"]
    assert response_blocks[0]["queue_position"] == 4
    assert response_blocks[1] == RECEIPT_BLOCK

    transcript = await client.get(f"/v1/conversations/{conversation_id}")
    assert transcript.status_code == 200
    stored_blocks = transcript.json()["messages"][1]["blocks"]
    stored_handoff = stored_blocks[0]
    stored_question = stored_handoff["summary"]["open_questions"][0]["text"]
    assert RAW_DOCUMENT not in stored_question
    assert "[DOC_1]" in stored_question
    assert stored_handoff["queue_position"] == 4
    assert type(stored_handoff["queue_position"]) is int
    assert stored_handoff["receipt"]["action"] == "handoff.create"
    assert stored_blocks[1]["receipt"]["action"] == "card.block"

    raw_state = await redis.get(f"orch:conv:{conversation_id}")
    assert raw_state is not None
    assert RAW_DOCUMENT.encode() not in raw_state


# --------------------------------------------------------------- client retries


def _message_url(conversation_id: str) -> str:
    return f"/v1/conversations/{conversation_id}/messages"


def _engine_handler(llm: ScriptedLLM, settings: Settings) -> EngineTurnHandler:
    engine = TurnEngine(
        llm=llm,
        banking=BankingCoreClient(base_url=BANKING_URL, settings=settings),
        collect_eval=settings.eval_expose_turn,
    )
    return EngineTurnHandler(engine)


BLOCK_CALL = {"card_ref": "card_ab12cd34", "reason": "LOST"}


async def test_retry_after_a_failed_turn_reuses_the_write_idempotency_key(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    fake_banking = FakeBankingCore()
    banking.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=fake_banking)
    settings = Settings()
    # card.block runs, then the LLM fails (the script has no next step): 503.
    failing = ScriptedLLM(
        [Step(tool_calls=[tool_call("call_lost", "card_block", BLOCK_CALL)])]
    )
    handler = _engine_handler(failing, settings)
    client = make_client(build_app(redis, handler))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]
    body = {"text": "Bloquea mi tarjeta", "client_message_id": "msg-0001-abcd"}

    failed = await client.post(_message_url(conversation_id), json=body)

    assert failed.status_code == 503
    assert len(fake_banking.calls_to("card.block")) == 1
    assert (await client.get(f"/v1/conversations/{conversation_id}")).json()[
        "messages"
    ] == []

    # The client retries the same message; the model now answers with new ids.
    handler.engine.llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_new", "card_block", BLOCK_CALL)]),
            Step(content="Listo: bloqueé tu tarjeta."),
        ]
    )
    retried = await client.post(_message_url(conversation_id), json=body)

    assert retried.status_code == 200
    first, second = fake_banking.calls_to("card.block")
    assert first["idempotency_key"] == second["idempotency_key"]
    blocks = retried.json()["blocks"]
    assert [b["type"] for b in blocks] == ["text", "receipt"]
    transcript = (await client.get(f"/v1/conversations/{conversation_id}")).json()
    assert [m["role"] for m in transcript["messages"]] == ["user", "assistant"]


async def test_a_new_message_id_is_a_new_write(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    fake_banking = FakeBankingCore()
    banking.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=fake_banking)
    llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_1", "card_block", BLOCK_CALL)]),
            Step(content="Bloqueada."),
            Step(tool_calls=[tool_call("call_2", "card_block", BLOCK_CALL)]),
            Step(content="Bloqueada otra vez."),
        ]
    )
    client = make_client(build_app(redis, _engine_handler(llm, Settings())))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]

    for message_id in ("msg-0001-abcd", "msg-0002-abcd"):
        response = await client.post(
            _message_url(conversation_id),
            json={"text": "Bloquea mi tarjeta", "client_message_id": message_id},
        )
        assert response.status_code == 200

    first, second = fake_banking.calls_to("card.block")
    assert first["idempotency_key"] != second["idempotency_key"]


async def test_duplicate_of_the_completed_turn_returns_its_outcome_without_running(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    fake_banking = FakeBankingCore()
    banking.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=fake_banking)
    llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_1", "card_block", BLOCK_CALL)]),
            Step(content="Registré tu documento [DOC_1] y bloqueé la tarjeta."),
        ]
    )
    settings = Settings(eval_expose_turn=True)
    client = make_client(
        build_app(redis, _engine_handler(llm, settings), settings=settings)
    )
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]
    body = {
        "text": f"Mi cédula es {RAW_DOCUMENT}, bloquea mi tarjeta",
        "client_message_id": "msg-0001-abcd",
    }

    first = await client.post(_message_url(conversation_id), json=body)
    second = await client.post(_message_url(conversation_id), json=body)

    assert first.status_code == second.status_code == 200
    assert (
        f"Registré tu documento {RAW_DOCUMENT} y" in first.json()["blocks"][0]["text"]
    )
    assert second.json()["blocks"] == first.json()["blocks"]
    assert "eval" in first.json()
    assert "eval" not in second.json()
    assert len(llm.calls) == 2  # the first turn's two completions, none for the retry
    assert len(fake_banking.calls_to("card.block")) == 1
    transcript = (await client.get(f"/v1/conversations/{conversation_id}")).json()
    assert [m["role"] for m in transcript["messages"]] == ["user", "assistant"]
    state = json.loads(await redis.get(f"orch:conv:{conversation_id}"))
    assert len(state["llm_history"]) == 4  # user, tool call, tool result, reply


async def test_stored_outcome_never_holds_raw_pii(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    class EchoHandler:
        """Replies with the customer's own values, in text and in a handoff."""

        calls = 0

        async def handle_turn(
            self,
            conversation: ConversationState,
            user_text: str,
            turn_id: str | None = None,
        ) -> TurnOutcome:
            type(self).calls += 1
            conversation.placeholder_map["[DOC_1]"] = RAW_DOCUMENT
            conversation.placeholder_map["[NAME_1]"] = RAW_NAME
            handoff = {
                "type": "handoff",
                "handoff_id": "hnd_abcd1234",
                "status": "QUEUED",
                "department": "DISPUTES",
                "priority": "HIGH",
                "queue_position": 4,
                "summary": {
                    "verified_facts": {"verification_state": "VERIFIED"},
                    "actions_taken": [],
                    "verification_method": "document_match_and_otp",
                    "open_questions": [
                        {
                            "source": "model_unverified",
                            "text": f"{RAW_NAME} asks about document {RAW_DOCUMENT}.",
                        }
                    ],
                },
                "receipt": {**RECEIPT_BLOCK["receipt"], "action": "handoff.create"},
            }
            return TurnOutcome(
                blocks=[
                    {
                        "type": "text",
                        "text": f"Hola {RAW_NAME}, documento {RAW_DOCUMENT}.",
                    },
                    {"type": "text", "text": "Segundo párrafo."},
                    handoff,
                    RECEIPT_BLOCK,
                ],
                metadata={},
            )

    client = make_client(build_app(redis, EchoHandler()))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]
    body = {"text": "Necesito ayuda", "client_message_id": "msg-0001-abcd"}

    first = await client.post(_message_url(conversation_id), json=body)
    second = await client.post(_message_url(conversation_id), json=body)

    assert EchoHandler.calls == 1  # the second answer came from the stored outcome
    assert second.json() == first.json()
    assert RAW_DOCUMENT in json.dumps(second.json()["blocks"])
    assert RAW_NAME in second.json()["blocks"][0]["text"]
    raw_state = await redis.get(f"orch:conv:{conversation_id}")
    assert raw_state is not None
    assert RAW_DOCUMENT.encode() not in raw_state
    assert RAW_NAME.encode() not in raw_state
    stored = json.loads(raw_state)["last_turn"]
    assert stored["client_message_id"] == "msg-0001-abcd"
    assert stored["blocks"][0]["text"] == "Hola [NAME_1], documento [DOC_1]."


async def test_message_ids_scope_which_requests_are_deduplicated(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    handler = FakeTurnHandler()
    client = make_client(build_app(redis, handler))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]
    url = _message_url(conversation_id)

    async def send(message_id: str | None) -> Any:
        body: dict[str, Any] = {"text": "hola"}
        if message_id is not None:
            body["client_message_id"] = message_id
        response = await client.post(url, json=body)
        assert response.status_code == 200
        return response

    await send("msg-A-000001")
    await send("msg-A-000001")  # duplicate of the last completed turn
    assert len(handler.calls) == 1
    await send("msg-B-000001")
    await send("msg-B-000001")  # duplicate
    assert len(handler.calls) == 2
    await send(None)  # no id: never deduplicated, and it becomes the last turn
    await send(None)
    assert len(handler.calls) == 4
    await send("msg-B-000001")  # no longer the last completed turn: runs again
    assert len(handler.calls) == 5

    turn_a, turn_b, none_1, none_2, turn_b_again = handler.turn_ids
    assert turn_a is not None and turn_b is not None
    assert turn_a != turn_b
    assert none_1 is None and none_2 is None
    assert turn_b_again == turn_b


async def test_a_failed_turn_is_not_a_completed_turn(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    handler = FakeTurnHandler(fail=True)
    client = make_client(build_app(redis, handler))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]
    body = {"text": "hola", "client_message_id": "msg-0001-abcd"}

    assert (
        await client.post(_message_url(conversation_id), json=body)
    ).status_code == 503
    handler.fail = False
    retried = await client.post(_message_url(conversation_id), json=body)

    assert retried.status_code == 200
    assert len(handler.calls) == 2
    assert handler.turn_ids[0] == handler.turn_ids[1]


async def test_the_turn_id_of_a_message_is_stable_per_conversation(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    handler = FakeTurnHandler()
    client = make_client(build_app(redis, handler))
    body = {"text": "hola", "client_message_id": "msg-0001-abcd"}
    ids = []
    for _ in range(2):  # two conversations, same client message id
        conversation_id = (await client.post("/v1/conversations")).json()[
            "conversation_id"
        ]
        await client.post(_message_url(conversation_id), json=body)
        ids.append(derive_turn_id(conversation_id, "msg-0001-abcd"))

    assert handler.turn_ids == ids
    assert ids[0] != ids[1]
    assert all(re.fullmatch(r"[0-9a-f]{32}", turn_id) for turn_id in ids)


@pytest.mark.parametrize(
    "message_id",
    ["abcdefgh", "a" * 64, "0123-4567_89ab", "A1_b2-C3_d4"],
)
async def test_valid_client_message_ids_are_accepted(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any, message_id: str
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler()))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]

    response = await client.post(
        _message_url(conversation_id),
        json={"text": "hola", "client_message_id": message_id},
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "message_id",
    [
        "",
        "abcdefg",
        "a" * 65,
        "abcd efgh",
        "abcdefgh\n",
        "abcdefg.",
        "abcdefg!",
        "áéíóúñab",
        "abc/defg",
        12345678,
        ["abcdefgh"],
    ],
)
async def test_invalid_client_message_ids_are_rejected(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any, message_id: Any
) -> None:
    handler = FakeTurnHandler()
    client = make_client(build_app(redis, handler))
    conversation_id = (await client.post("/v1/conversations")).json()["conversation_id"]

    response = await client.post(
        _message_url(conversation_id),
        json={"text": "hola", "client_message_id": message_id},
    )

    assert response.status_code == 422
    assert handler.calls == []


def test_turn_ids_derived_from_message_ids_are_deterministic() -> None:
    turn_id = derive_turn_id("conv_1", "msg-0001-abcd")

    assert turn_id == derive_turn_id("conv_1", "msg-0001-abcd")
    assert turn_id != derive_turn_id("conv_2", "msg-0001-abcd")
    assert turn_id != derive_turn_id("conv_1", "msg-0002-abcd")


# --- Market (ADR-0014) ---


async def test_a_locale_sets_the_language_and_is_kept(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(reply="ok")))
    created = (await client.post("/v1/conversations", json={"locale": "es-MX"})).json()
    assert created["language"] == "es" and created["locale"] == "es-MX"
    transcript = await client.get(f"/v1/conversations/{created['conversation_id']}")
    assert transcript.json()["locale"] == "es-MX"


@pytest.mark.parametrize(
    "body", [{"lang": "pt", "locale": "es-AR"}, {"locale": "es-ES"}, {"locale": "MX"}]
)
async def test_a_contradicting_or_unknown_locale_is_a_422(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any, body: dict
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(reply="ok")))
    assert (await client.post("/v1/conversations", json=body)).status_code == 422


async def test_switching_language_drops_the_market(
    redis: fakeredis.FakeAsyncRedis, banking: Any, make_client: Any
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(reply="ok")))
    conv = (await client.post("/v1/conversations", json={"locale": "pt-BR"})).json()
    url = f"/v1/conversations/{conv['conversation_id']}"
    await client.post(f"{url}/messages", json={"text": "olá", "lang": "pt"})
    assert (await client.get(url)).json()["locale"] == "pt-BR"
    await client.post(f"{url}/messages", json={"text": "hola", "lang": "es"})
    after = (await client.get(url)).json()
    assert after["language"] == "es" and after["locale"] is None
