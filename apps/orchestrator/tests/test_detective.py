"""Detective mode (ADR-0019): each turn's timeline, masked, the turn unchanged."""

import json
from typing import Any

import fakeredis
import httpx
import pytest
import respx
from contracts.trace import TurnTrace
from fastapi import FastAPI
from orchestrator.chat.engine_handler import EngineTurnHandler
from orchestrator.chat.routes import _takeover_trace
from orchestrator.config import Settings
from orchestrator.conversation import TurnEngine
from orchestrator.detective import DetectiveSwitch, DetectiveUnavailableError
from orchestrator.main import create_app
from orchestrator.session.crypto import PlaceholderEncryptor
from orchestrator.session.store import SessionStore
from orchestrator.tools_client import BankingCoreClient

from .fake_llm import ScriptedLLM, Step, tool_call
from .test_conversation_engine import (
    ANALYZE_OK,
    BANKING_URL,
    ENCODER_URL,
    RAW_DOCUMENT,
    FakeBankingCore,
    make_engine,
    new_context,
)

TEXT = f"Perdí mi tarjeta, mi cédula es {RAW_DOCUMENT}"


def identify_then_answer() -> ScriptedLLM:
    return ScriptedLLM(
        [
            Step(
                tool_calls=[
                    tool_call(
                        "call_1",
                        "customer_match",
                        {"document_type": "NATIONAL_ID", "document_number": "[DOC_1]"},
                    )
                ]
            ),
            Step(content="Te identifiqué. ¿Bloqueamos la tarjeta?"),
        ]
    )


@pytest.fixture
def services() -> Any:
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=FakeBankingCore())
        router.post(f"{ENCODER_URL}/v1/analyze").mock(
            return_value=httpx.Response(200, json=ANALYZE_OK)
        )
        router.post(f"{BANKING_URL}/v1/sessions").mock(
            return_value=httpx.Response(201, json={"session_id": "sess_opaque_0001"})
        )
        yield router


def traced(llm: ScriptedLLM) -> TurnEngine:
    engine = make_engine(llm)
    engine.collect_trace = True
    return engine


# --------------------------------------------------------------------- engine


async def test_off_the_turn_has_no_trace(services: Any) -> None:
    result = await make_engine(identify_then_answer()).run_turn(new_context(), TEXT)
    assert result.trace is None


async def test_on_every_step_is_an_event_in_order(services: Any) -> None:
    result = await traced(identify_then_answer()).run_turn(new_context(), TEXT)
    trace = result.trace
    assert trace is not None
    assert [event.kind.value for event in trace.events] == [
        "encoder",
        "masking",
        "llm_call",
        "tool_call",
        "llm_call",
        "blocks",
        "decisions",
    ]
    assert [event.seq for event in trace.events] == list(range(7))
    assert trace.tool_rounds == 1
    assert all(event.start_ms <= trace.total_ms for event in trace.events)

    encoder, masking, first, tool, second, blocks, _ = trace.events
    assert encoder.encoder is not None
    assert encoder.encoder.intent == "report_lost_card"
    assert encoder.encoder.server_latency_ms == 12.0
    assert encoder.duration_ms is not None

    assert masking.masking is not None
    assert masking.masking.placeholders == ["[DOC_1]"]
    assert "[DOC_1]" in (masking.masking.masked_text or "")

    assert first.llm_call is not None and second.llm_call is not None
    assert first.llm_call.messages_from == 0
    assert first.llm_call.messages[0].role == "system"
    # The second call lists only what was added since the first: no system prompt again.
    assert second.llm_call.messages_from > 0
    assert all(message.role != "system" for message in second.llm_call.messages)
    assert first.llm_call.response_tool_calls[0].name == "customer_match"
    assert second.llm_call.response_content == "Te identifiqué. ¿Bloqueamos la tarjeta?"

    assert tool.tool_call is not None
    assert tool.tool_call.tool == "customer.match"
    assert tool.tool_call.executed is True
    assert tool.status.value == "ok"
    assert json.loads(tool.tool_call.arguments or "{}")["document_number"] == "[DOC_1]"
    assert json.loads(tool.tool_call.feedback or "{}")["status"] == "ok"

    assert blocks.blocks is not None
    assert blocks.blocks.kept == ["text"]
    assert blocks.blocks.fallback is False


async def test_the_trace_changes_nothing_the_provider_or_banking_core_sees(
    services: Any,
) -> None:
    off_llm, on_llm = identify_then_answer(), identify_then_answer()
    off = await make_engine(off_llm).run_turn(new_context(), TEXT, turn_id="t1")
    on = await traced(on_llm).run_turn(new_context(), TEXT, turn_id="t1")

    assert on_llm.calls == off_llm.calls
    assert on.metadata.llm_recording_keys == off.metadata.llm_recording_keys
    assert [b.model_dump() for b in on.blocks] == [b.model_dump() for b in off.blocks]


async def test_no_raw_customer_value_is_in_the_trace(services: Any) -> None:
    result = await traced(identify_then_answer()).run_turn(new_context(), TEXT)
    assert result.trace is not None
    dumped = result.trace.model_dump_json()
    assert RAW_DOCUMENT not in dumped
    assert "[DOC_1]" in dumped


async def test_a_refused_tool_is_a_refused_event(services: Any) -> None:
    services.post(f"{BANKING_URL}/v1/tools/call").mock(
        side_effect=FakeBankingCore(refuse={"customer.match": "NOT_MATCHED"})
    )
    result = await traced(identify_then_answer()).run_turn(new_context(), TEXT)
    assert result.trace is not None
    tool = next(e for e in result.trace.events if e.kind.value == "tool_call")
    assert tool.status.value == "refused"
    assert tool.tool_call is not None
    assert tool.tool_call.reason_code is not None
    assert tool.tool_call.reason_code.value == "NOT_MATCHED"


async def test_an_unknown_tool_is_refused_locally_and_said_why(services: Any) -> None:
    llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_1", "wire_money", {"amount": 1})]),
            Step(content="No puedo hacer eso."),
        ]
    )
    result = await traced(llm).run_turn(new_context(), "manda plata")
    assert result.trace is not None
    tool = next(e for e in result.trace.events if e.kind.value == "tool_call")
    assert tool.tool_call is not None
    assert tool.tool_call.executed is False
    assert tool.tool_call.local_reason == "the model named a tool that does not exist"


async def test_the_takeover_trace_is_one_note() -> None:
    trace = _takeover_trace()
    assert trace is not None
    assert [event.kind.value for event in trace.events] == ["takeover"]
    assert trace.events[0].note


# ------------------------------------------------------------------- the switch


async def test_the_switch_is_off_when_unavailable_and_on_by_default() -> None:
    redis = fakeredis.FakeAsyncRedis()
    assert await DetectiveSwitch(False, redis, "k").enabled() is False
    with pytest.raises(DetectiveUnavailableError):
        await DetectiveSwitch(False, redis, "k").set(True)

    switch = DetectiveSwitch(True, redis, "k")
    assert await switch.enabled() is True
    assert await switch.set(False) is False
    assert await switch.enabled() is False
    # Another process reading the same key sees the same state.
    assert await DetectiveSwitch(True, redis, "k").enabled() is False
    await switch.set(True)
    assert await switch.enabled() is True


async def test_an_unreadable_switch_falls_back_to_on() -> None:
    class Broken:
        async def get(self, key: str) -> None:
            raise ConnectionError("down")

    assert await DetectiveSwitch(True, Broken(), "k").enabled() is True  # type: ignore[arg-type]


# ----------------------------------------------------------------- the chat API


def build_app(redis: fakeredis.FakeAsyncRedis, settings: Settings) -> FastAPI:
    store = SessionStore(
        redis=redis,
        encryptor=PlaceholderEncryptor("test-secret"),
        ttl_seconds=3600,
        lock_timeout_seconds=30,
    )
    llm = ScriptedLLM([Step(content="Hola, ¿en qué te ayudo?")], repeat_last=True)
    engine = TurnEngine(
        llm=llm,
        banking=BankingCoreClient(base_url=BANKING_URL, settings=settings),
        collect_trace=settings.detective_mode,
    )
    return create_app(
        settings=settings,
        session_store=store,
        banking_client=BankingCoreClient(base_url=BANKING_URL, settings=settings),
        turn_handler=EngineTurnHandler(engine),
    )


async def _turn(app: FastAPI) -> tuple[dict[str, Any], dict[str, Any]]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://orch") as client:
        capabilities = (await client.get("/v1/capabilities")).json()
        conversation = (await client.post("/v1/conversations")).json()
        url = f"/v1/conversations/{conversation['conversation_id']}/messages"
        answer = await client.post(url, json={"text": "hola"})
        assert answer.status_code == 200
        return capabilities, answer.json()


async def test_api_off_no_trace_and_capabilities_say_so(services: Any) -> None:
    capabilities, answer = await _turn(
        build_app(fakeredis.FakeAsyncRedis(), Settings(encoder_enabled=False))
    )
    assert capabilities == {"detective": False}
    assert "trace" not in answer


async def test_api_on_the_turn_carries_its_trace(services: Any) -> None:
    capabilities, answer = await _turn(
        build_app(
            fakeredis.FakeAsyncRedis(),
            Settings(encoder_enabled=False, detective_mode=True),
        )
    )
    assert capabilities == {"detective": True}
    trace = TurnTrace.model_validate(answer["trace"])
    assert [e.kind.value for e in trace.events][-2:] == ["blocks", "decisions"]


async def test_api_switched_off_at_runtime_no_trace(services: Any) -> None:
    app = build_app(
        fakeredis.FakeAsyncRedis(), Settings(encoder_enabled=False, detective_mode=True)
    )
    await app.state.detective.set(False)
    capabilities, answer = await _turn(app)
    assert capabilities == {"detective": False}
    assert "trace" not in answer


def test_detective_mode_is_allowed_in_production_unlike_the_eval_hook() -> None:
    production = {
        "app_env": "production",
        "session_secret": "a-real-session-secret",
        "detective_mode": True,
    }
    app = create_app(
        settings=Settings(**production),
        session_store=SessionStore(
            redis=fakeredis.FakeAsyncRedis(),
            encryptor=PlaceholderEncryptor("test-secret"),
            ttl_seconds=3600,
            lock_timeout_seconds=30,
        ),
    )
    assert app.state.detective.available is True
    with pytest.raises(ValueError, match="EVAL_EXPOSE_TURN"):
        create_app(settings=Settings(**production, eval_expose_turn=True))


# ------------------------------------------------- the back office's switch


AGENT_TOKEN = "agent-test-token-0123456789"
AGENT_AUTH = {"Authorization": f"Bearer {AGENT_TOKEN}"}


def agent_app(detective_mode: bool) -> FastAPI:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        encoder_enabled=False,
        agent_api_enabled=True,
        agent_api_token=AGENT_TOKEN,
        detective_mode=detective_mode,
    )
    return build_app(fakeredis.FakeAsyncRedis(), settings)


async def test_the_back_office_reads_and_flips_the_switch() -> None:
    app = agent_app(detective_mode=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://orch") as client:
        state = await client.get("/v1/agent/detective", headers=AGENT_AUTH)
        assert state.json() == {"available": True, "enabled": True}

        off = await client.put(
            "/v1/agent/detective", json={"enabled": False}, headers=AGENT_AUTH
        )
        assert off.json() == {"available": True, "enabled": False}
        assert (await client.get("/v1/capabilities")).json() == {"detective": False}

        on = await client.put(
            "/v1/agent/detective", json={"enabled": True}, headers=AGENT_AUTH
        )
        assert on.json() == {"available": True, "enabled": True}
        assert (await client.get("/v1/capabilities")).json() == {"detective": True}


async def test_the_switch_cannot_go_beyond_what_the_environment_offers() -> None:
    app = agent_app(detective_mode=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://orch") as client:
        state = await client.get("/v1/agent/detective", headers=AGENT_AUTH)
        assert state.json() == {"available": False, "enabled": False}
        refused = await client.put(
            "/v1/agent/detective", json={"enabled": True}, headers=AGENT_AUTH
        )
        assert refused.status_code == 409
        assert refused.json()["detail"] == "detective_unavailable"


async def test_the_switch_needs_the_agent_token() -> None:
    app = agent_app(detective_mode=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://orch") as client:
        assert (await client.get("/v1/agent/detective")).status_code == 401
        put = await client.put("/v1/agent/detective", json={"enabled": False})
        assert put.status_code == 401
        extra = await client.put(
            "/v1/agent/detective",
            json={"enabled": False, "who": "x"},
            headers=AGENT_AUTH,
        )
        assert extra.status_code == 422
