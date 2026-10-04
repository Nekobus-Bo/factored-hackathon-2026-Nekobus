"""Turn engine tests: fake LLM, respx for banking-core and the encoder.

Covers the happy path (identify -> OTP -> verify -> card.block receipt),
a refusal relayed without retry, encoder degrade, the tool-round bound, the
block allowlist, and that raw PII never reaches the provider payload.
"""

import json
import logging
from typing import Any

import httpx
import pytest
import respx
from contracts import HandoffBlock, ReceiptBlock, TextBlock, ToolResult
from contracts.envelope import FlowHint
from orchestrator.config import Settings
from orchestrator.conversation import ConversationContext, TurnEngine
from orchestrator.conversation.prompt import (
    FALLBACK_MESSAGES,
    IDENTITY_REQUEST_ASK,
    IDENTITY_REQUEST_OPENINGS,
    REPHRASE_MESSAGES,
)
from orchestrator.encoder_client import EncoderClient
from orchestrator.tools_client import BankingCoreClient

from .fake_llm import ScriptedLLM, Step, tool_call

BANKING_URL = "http://banking-core.test"
ENCODER_URL = "http://encoder.test"
SESSION_ID = "sess_opaque_0001"

RAW_DOCUMENT = "1020304050"
RAW_OTP = "123456"


def receipt(action: str, target: str, before: str, after: str) -> dict[str, Any]:
    return {
        "action": action,
        "target_masked": target,
        "state_before": before,
        "state_after": after,
        "verified_at": "2026-09-27T12:00:00Z",
        "audit_id": "aud_0001abcd",
    }


OK_DATA: dict[str, dict[str, Any]] = {
    "customer.match": {"matched": True},
    "otp.send": {
        "sent": True,
        "challenge_id": "chal_abcdef01",
        "channel": "SIMULATED",
        "destination_masked": "simulated",
        "expires_in_seconds": 300,
        "receipt": receipt("otp.send", "chal_abcdef01", "NONE", "ISSUED"),
    },
    "otp.verify": {
        "verified": True,
        "state": "VERIFIED",
        "attempts_remaining": 2,
        "receipt": receipt("otp.verify", "chal_abcdef01", "OTP_PENDING", "VERIFIED"),
    },
    "card.list": {
        "cards": [
            {
                "card_ref": "card_ab12cd34",
                "masked_pan": "**** **** **** 1234",
                "card_type": "DEBIT",
                "status": "ACTIVE",
                "expiry_month": 12,
                "expiry_year": 2028,
            }
        ]
    },
    "card.block": {
        "card_ref": "card_ab12cd34",
        "status": "BLOCKED",
        "receipt": receipt("card.block", "card_ab12cd34", "ACTIVE", "BLOCKED"),
    },
    "kb.search": {"results": []},
    "handoff.create": {
        "handoff_id": "hnd_abcd1234",
        "status": "QUEUED",
        "department": "DISPUTES",
        "priority": "HIGH",
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
                    "text": "Server-stored handoff question.",
                }
            ],
        },
        "queue_position": 4,
        "created_at": "2026-09-27T12:00:00Z",
        "receipt": receipt("handoff.create", "hnd_abcd1234", "NONE", "QUEUED"),
    },
}


class FakeBankingCore:
    """respx side effect: answers per tool and records every request."""

    def __init__(
        self,
        refuse: dict[str, str] | None = None,
        data: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.refuse = refuse or {}
        self.data = {**OK_DATA, **(data or {})}
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(
            {"session": request.headers.get("X-Session-Id"), "body": body}
        )
        tool = body["tool"]
        if tool in self.refuse:
            payload = {
                "tool": tool,
                "status": "refused",
                "reason_code": self.refuse[tool],
                "data": None,
            }
        else:
            payload = {"tool": tool, "status": "ok", "data": self.data[tool]}
        return httpx.Response(200, json=payload)

    def calls_to(self, tool: str) -> list[dict[str, Any]]:
        return [r["body"] for r in self.requests if r["body"]["tool"] == tool]


ANALYZE_OK = {
    "intent": "report_lost_card",
    "confidence": 0.93,
    "abstain": False,
    "slots": [],
    "pii_spans": [],
    "model_id": "encoder-test",
    "latency_ms": 12.0,
}


def make_engine(llm: ScriptedLLM, max_tool_rounds: int = 5) -> TurnEngine:
    settings = Settings()
    return TurnEngine(
        llm=llm,
        banking=BankingCoreClient(base_url=BANKING_URL, settings=settings),
        encoder=EncoderClient(base_url=ENCODER_URL, timeout=1.0, settings=settings),
        max_tool_rounds=max_tool_rounds,
    )


def new_context() -> ConversationContext:
    return ConversationContext(session_id=SESSION_ID, language="es")


def assert_no_dangling_tool_calls(history: list[dict[str, Any]]) -> None:
    call_ids = {
        tc["id"]
        for m in history
        if m["role"] == "assistant"
        for tc in m.get("tool_calls", [])
    }
    answered = {m["tool_call_id"] for m in history if m["role"] == "tool"}
    assert call_ids == answered


@pytest.fixture
def mock_services() -> Any:
    with respx.mock(assert_all_called=False) as router:
        yield router


async def test_happy_path_es_identify_otp_verify_block(mock_services: Any) -> None:
    banking = FakeBankingCore()
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    llm = ScriptedLLM(
        [
            # Turn 1: identify, then send the OTP
            Step(
                tool_calls=[
                    tool_call(
                        "call_1",
                        "customer_match",
                        {"document_type": "NATIONAL_ID", "document_number": "[DOC_1]"},
                    )
                ]
            ),
            Step(tool_calls=[tool_call("call_2", "otp_send", {})]),
            Step(content="Te envié un código de verificación. ¿Me lo compartes?"),
            # Turn 2: verify, list cards, block
            Step(tool_calls=[tool_call("call_3", "otp_verify", {"code": "[OTP_1]"})]),
            Step(tool_calls=[tool_call("call_4", "card_list", {})]),
            Step(
                tool_calls=[
                    tool_call(
                        "call_5",
                        "card_block",
                        {"card_ref": "card_ab12cd34", "reason": "LOST"},
                    )
                ]
            ),
            Step(content="Listo: bloqueé tu tarjeta terminada en 1234."),
        ]
    )
    engine = make_engine(llm)
    context = new_context()

    first = await engine.run_turn(
        context, f"Hola, perdí mi tarjeta. Mi cédula es {RAW_DOCUMENT}", turn_id="t1"
    )
    second = await engine.run_turn(context, f"El código es {RAW_OTP}", turn_id="t2")

    # banking-core received rehydrated values, on the pinned session
    assert {r["session"] for r in banking.requests} == {SESSION_ID}
    match_call = banking.calls_to("customer.match")[0]
    assert match_call["args"]["document_number"] == RAW_DOCUMENT
    assert banking.calls_to("otp.verify")[0]["args"]["code"] == RAW_OTP
    block_call = banking.calls_to("card.block")[0]
    assert block_call["args"] == {
        "card_ref": "card_ab12cd34",
        "reason": "LOST",
        "transaction_id": None,
    }
    assert block_call["idempotency_key"].startswith("pb-")
    assert match_call.get("idempotency_key") is None
    assert [r["body"]["tool"] for r in banking.requests] == [
        "customer.match",
        "otp.send",
        "otp.verify",
        "card.list",
        "card.block",
    ]

    # Turn 1 metadata carries the encoder signal
    assert first.metadata.encoder is not None
    assert first.metadata.encoder.intent == "report_lost_card"
    assert first.metadata.encoder_unavailable is False
    assert first.metadata.tool_rounds == 2

    # Turn 2 ends with the text and the card.block receipt
    assert second.metadata.tool_rounds == 3
    assert isinstance(second.blocks[0], TextBlock)
    assert second.blocks[0].text == "Listo: bloqueé tu tarjeta terminada en 1234."
    receipts = [b for b in second.blocks if isinstance(b, ReceiptBlock)]
    assert [r.receipt.action for r in receipts] == ["otp.verify", "card.block"]
    assert receipts[-1].receipt.state_after.value == "BLOCKED"

    # PII: never in any provider payload nor in history; only server-side map
    payload = llm.payload_dump()
    history = json.dumps(context.history, ensure_ascii=False)
    for raw in (RAW_DOCUMENT, RAW_OTP):
        assert raw not in payload
        assert raw not in history
        assert raw in context.placeholder_map.values()
    assert "[DOC_1]" in payload and "[OTP_1]" in payload
    assert_no_dangling_tool_calls(context.history)

    # Tools offered come from the catalog, with stable function names
    offered = {t["function"]["name"] for t in llm.calls[0]["tools"]}
    assert {"card_block", "otp_verify", "customer_match"} <= offered


async def test_refusal_is_relayed_not_retried(mock_services: Any) -> None:
    banking = FakeBankingCore(refuse={"card.block": "STATE_NOT_ALLOWED"})
    route = mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    reply = "Primero necesito verificar tu identidad antes de bloquear la tarjeta."
    llm = ScriptedLLM(
        [
            Step(
                tool_calls=[
                    tool_call(
                        "call_1",
                        "card_block",
                        {"card_ref": "card_ab12cd34", "reason": "STOLEN"},
                    )
                ]
            ),
            Step(content=reply),
        ]
    )
    context = new_context()

    result = await make_engine(llm).run_turn(context, "Bloquea mi tarjeta ya")

    assert route.call_count == 1
    fed_back = llm.calls[1]["messages"][-1]
    assert fed_back["role"] == "tool"
    assert '"status": "refused"' in fed_back["content"]
    assert "STATE_NOT_ALLOWED" in fed_back["content"]
    outcome = result.metadata.tool_outcomes[0]
    assert (outcome.tool, outcome.status.value, outcome.executed) == (
        "card.block",
        "refused",
        True,
    )
    assert result.blocks == [TextBlock(text=reply)]


@pytest.mark.parametrize(
    "encoder_response",
    [httpx.Response(503, json={"detail": "uncalibrated"}), httpx.ReadTimeout("slow")],
    ids=["503", "timeout"],
)
async def test_encoder_unavailable_degrades_to_llm_only(
    mock_services: Any, encoder_response: Any
) -> None:
    route = mock_services.post(f"{ENCODER_URL}/v1/analyze")
    if isinstance(encoder_response, Exception):
        route.mock(side_effect=encoder_response)
    else:
        route.mock(return_value=encoder_response)
    llm = ScriptedLLM([Step(content="¿En qué te puedo ayudar?")])

    result = await make_engine(llm).run_turn(new_context(), "Hola")

    assert result.metadata.encoder_unavailable is True
    assert result.metadata.encoder is None
    assert result.blocks == [TextBlock(text="¿En qué te puedo ayudar?")]
    assert len(llm.calls) == 1


async def test_no_encoder_configured_is_not_a_degrade() -> None:
    llm = ScriptedLLM([Step(content="Hola")])
    engine = TurnEngine(
        llm=llm,
        banking=BankingCoreClient(base_url=BANKING_URL, settings=Settings()),
        encoder=None,
    )

    result = await engine.run_turn(new_context(), "Hola")

    assert result.metadata.encoder_unavailable is False
    assert result.metadata.encoder is None


async def test_max_tool_rounds_bounds_the_loop(mock_services: Any) -> None:
    banking = FakeBankingCore()
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    llm = ScriptedLLM(
        [Step(tool_calls=[tool_call("call_kb", "kb_search", {"query": "tarjeta"})])],
        repeat_last=True,
    )
    context = new_context()

    result = await make_engine(llm, max_tool_rounds=2).run_turn(context, "Ayuda")

    assert len(banking.calls_to("kb.search")) == 2
    assert len(llm.calls) == 3
    assert result.metadata.max_tool_rounds_reached is True
    assert result.metadata.tool_rounds == 2
    assert result.blocks == [TextBlock(text=FALLBACK_MESSAGES["es"])]
    assert context.history[-1] == {
        "role": "assistant",
        "content": FALLBACK_MESSAGES["es"],
    }
    assert_no_dangling_tool_calls(context.history)


async def test_model_blocks_outside_allowlist_are_dropped(
    mock_services: Any, caplog: pytest.LogCaptureFixture
) -> None:
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    forged = receipt("card.block", "card_ab12cd34", "ACTIVE", "BLOCKED")
    content = json.dumps(
        {
            "blocks": [
                {"type": "text", "text": "Tu tarjeta ya está bloqueada."},
                {"type": "receipt", "receipt": forged},
                {"type": "button", "label": "Confirmar"},
                {"type": "text", "text": "x", "html": "<b>x</b>"},
            ]
        }
    )
    llm = ScriptedLLM([Step(content=content)])

    with caplog.at_level(logging.WARNING):
        result = await make_engine(llm).run_turn(new_context(), "Hola")

    assert result.blocks == [TextBlock(text="Tu tarjeta ya está bloqueada.")]
    assert sorted(result.metadata.dropped_block_types) == ["button", "receipt", "text"]
    assert "Dropped non-allowlisted model blocks" in caplog.text
    assert "Confirmar" not in caplog.text


# The reply gpt-6-luna gave on Cloud Run (2026-10-03): the opening flow line,
# translated, then the answer it meant.
LEAKED_REPLY = (
    "banking-core flow: sesión ANONYMOUS; el siguiente paso es `customer_match`. "
    "Para reportar y bloquear una tarjeta robada, primero necesito verificar tu "
    "identidad. ¿Qué tipo de documento tienes y cuál es su número?\n"
    "Lamento que te haya pasado. Para ayudarte a bloquear la tarjeta robada, "
    "primero necesito verificar tu identidad. ¿Qué tipo de documento tienes y cuál "
    "es su número?"
)


async def test_a_reply_line_naming_the_flow_never_reaches_the_customer(
    mock_services: Any, caplog: pytest.LogCaptureFixture
) -> None:
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    llm = ScriptedLLM([Step(content=LEAKED_REPLY)])
    context = new_context()

    with caplog.at_level(logging.WARNING):
        result = await make_engine(llm).run_turn(context, "me robaron la tarjeta")

    answer = LEAKED_REPLY.split("\n")[1]
    assert result.blocks == [TextBlock(text=answer)]
    assert result.metadata.internal_lines_withheld == 1
    # Nor the history the next completion reads; the log has a count, not the text.
    remembered = context.history[-1]["content"]
    assert remembered.startswith("Lamento que te haya pasado.")
    assert "banking-core" not in remembered and "customer_match" not in remembered
    assert "Withheld 1 reply line(s)" in caplog.text
    assert "ANONYMOUS" not in caplog.text


async def test_a_reply_made_only_of_internal_lines_becomes_the_fallback(
    mock_services: Any,
) -> None:
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    content = json.dumps(
        {"blocks": [{"type": "text", "text": "Next: otp.send, then otp_verify."}]}
    )
    llm = ScriptedLLM([Step(content=content)])

    result = await make_engine(llm).run_turn(new_context(), "hola")

    assert result.blocks == [TextBlock(text=FALLBACK_MESSAGES["es"])]
    assert result.metadata.internal_lines_withheld == 1


async def test_an_ordinary_reply_is_left_as_written(mock_services: Any) -> None:
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    content = "Your identity is verified.\nThe card is locked now; anything else?"
    llm = ScriptedLLM([Step(content=content)])
    context = new_context()

    result = await make_engine(llm).run_turn(context, "thanks")

    assert result.blocks == [TextBlock(text=content)]
    assert result.metadata.internal_lines_withheld == 0
    assert context.history[-1] == {"role": "assistant", "content": content}


async def test_invalid_or_unknown_tool_calls_never_reach_banking_core(
    mock_services: Any,
) -> None:
    route = mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(
        side_effect=FakeBankingCore()
    )
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    llm = ScriptedLLM(
        [
            Step(
                tool_calls=[
                    tool_call("call_1", "card_block", {"card_ref": "x"}),
                    tool_call("call_2", "transfer_money", {"amount": 1}),
                    {
                        "id": "call_3",
                        "type": "function",
                        "function": {"name": "card_list", "arguments": "{not json"},
                    },
                ]
            ),
            Step(content="No pude hacerlo."),
        ]
    )
    context = new_context()

    result = await make_engine(llm).run_turn(context, "Bloquea mi tarjeta")

    assert route.call_count == 0
    outcomes = [
        (o.tool, o.reason_code.value if o.reason_code else None, o.executed)
        for o in result.metadata.tool_outcomes
    ]
    assert outcomes == [
        ("card.block", "INVALID_ARGUMENTS", False),
        ("transfer_money", "INVALID_ARGUMENTS", False),
        ("card.list", "INVALID_ARGUMENTS", False),
    ]
    assert_no_dangling_tool_calls(context.history)


async def test_literal_otp_from_model_is_rejected_and_masked_in_history(
    mock_services: Any,
) -> None:
    """A literal code is a guess: rejected locally, and still masked in history."""
    banking = FakeBankingCore()
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_1", "otp_verify", {"code": RAW_OTP})]),
            Step(content="Verificado."),
        ]
    )
    context = new_context()

    result = await make_engine(llm).run_turn(context, "Aquí está")

    assert banking.calls_to("otp.verify") == []
    outcome = result.metadata.tool_outcomes[0]
    assert (outcome.tool, outcome.executed) == ("otp.verify", False)
    assert outcome.reason_code is not None
    assert outcome.reason_code.value == "INVALID_ARGUMENTS"
    assert RAW_OTP not in json.dumps(context.history)
    assert RAW_OTP not in json.dumps(llm.calls[1]["messages"])


async def test_masking_failure_fails_closed_without_calling_out() -> None:
    llm = ScriptedLLM([])
    context = new_context()
    engine = TurnEngine(
        llm=llm,
        banking=BankingCoreClient(base_url=BANKING_URL, settings=Settings()),
    )

    result = await engine.run_turn(context, '{"code":123456}')

    assert result.metadata.masking_failed is True
    assert result.blocks == [TextBlock(text=REPHRASE_MESSAGES["es"])]
    assert llm.calls == []
    assert context.history == []


async def test_llm_failure_leaves_context_untouched() -> None:
    llm = ScriptedLLM([])
    context = new_context()
    engine = TurnEngine(
        llm=llm,
        banking=BankingCoreClient(base_url=BANKING_URL, settings=Settings()),
    )

    with pytest.raises(AssertionError, match="ran out of steps"):
        await engine.run_turn(context, f"Mi cédula es {RAW_DOCUMENT}")

    assert context.history == []
    assert context.placeholder_map == {}


def _mock_encoder(mock_services: Any) -> None:
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )


@pytest.mark.parametrize("reply", ["482913", "es 482913", "482 913", "482-913"])
async def test_bare_otp_is_masked_while_a_challenge_is_pending(
    mock_services: Any, reply: str
) -> None:
    banking = FakeBankingCore()
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_1", "otp_send", {})]),
            Step(content="Te envié un código."),
            Step(tool_calls=[tool_call("call_2", "otp_verify", {"code": "[OTP_1]"})]),
            Step(content="Verificado."),
        ]
    )
    engine = make_engine(llm)
    context = new_context()

    await engine.run_turn(context, "Quiero bloquear mi tarjeta")
    await engine.run_turn(context, reply)

    assert "482913" not in llm.payload_dump()
    assert "482913" not in json.dumps(context.history)
    assert "[OTP_1]" in llm.calls[2]["messages"][-1]["content"]
    assert banking.calls_to("otp.verify")[0]["args"]["code"] == "482913"


async def test_bare_digits_are_not_treated_as_otp_without_a_challenge(
    mock_services: Any,
) -> None:
    _mock_encoder(mock_services)
    llm = ScriptedLLM([Step(content="Entendido.")])
    context = new_context()

    await make_engine(llm).run_turn(context, "Fueron 2500 pesos")

    assert llm.calls[0]["messages"][-1]["content"] == "Fueron 2500 pesos"


async def test_refused_tool_is_not_executed_again_in_the_same_turn(
    mock_services: Any,
) -> None:
    banking = FakeBankingCore(refuse={"otp.verify": "STATE_NOT_ALLOWED"})
    route = mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    retry = tool_call("call_x", "otp_verify", {"code": "[OTP_1]"})
    llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_1", "otp_verify", {"code": "[OTP_1]"})]),
            Step(tool_calls=[retry]),
            Step(content="No pude verificar el código."),
        ]
    )
    context = new_context()

    result = await make_engine(llm).run_turn(context, f"El código es {RAW_OTP}")

    assert route.call_count == 1
    first, second = result.metadata.tool_outcomes
    assert (first.status.value, first.executed) == ("refused", True)
    assert (second.status.value, second.executed) == ("refused", False)
    assert second.reason_code == first.reason_code
    assert "STATE_NOT_ALLOWED" in llm.calls[2]["messages"][-1]["content"]
    assert_no_dangling_tool_calls(context.history)


async def test_otp_verify_runs_at_most_once_per_turn(mock_services: Any) -> None:
    wrong = {
        **OK_DATA["otp.verify"],
        "verified": False,
        "state": "OTP_PENDING",
        "receipt": receipt("otp.verify", "chal_abcdef01", "OTP_PENDING", "OTP_PENDING"),
    }
    banking = FakeBankingCore(data={"otp.verify": wrong})
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    verify = tool_call("call_v", "otp_verify", {"code": "[OTP_1]"})
    llm = ScriptedLLM([Step(tool_calls=[verify])] * 3 + [Step(content="Incorrecto.")])

    result = await make_engine(llm).run_turn(new_context(), f"El código es {RAW_OTP}")

    assert len(banking.calls_to("otp.verify")) == 1
    reasons = [
        (o.executed, o.reason_code.value if o.reason_code else None)
        for o in result.metadata.tool_outcomes
    ]
    assert reasons == [(True, None), (False, "RATE_LIMITED"), (False, "RATE_LIMITED")]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("otp_verify", {"code": "000001"}),
        ("otp_verify", {"code": "[OTP_9]"}),
        (
            "customer_match",
            {"document_type": "NATIONAL_ID", "document_number": "12345678"},
        ),
        (
            "customer_match",
            {"document_type": "NATIONAL_ID", "document_number": "[DOC_7]"},
        ),
    ],
    ids=["otp-literal", "otp-unmapped", "doc-literal", "doc-unmapped"],
)
async def test_secrets_accept_only_mapped_placeholders(
    mock_services: Any, name: str, args: dict[str, Any]
) -> None:
    route = mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(
        side_effect=FakeBankingCore()
    )
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
        [Step(tool_calls=[tool_call("call_1", name, args)]), Step(content="No.")]
    )

    result = await make_engine(llm).run_turn(new_context(), "Hola")

    assert route.call_count == 0
    outcome = result.metadata.tool_outcomes[0]
    assert outcome.executed is False
    assert outcome.reason_code is not None
    assert outcome.reason_code.value == "INVALID_ARGUMENTS"


@pytest.mark.parametrize(
    ("name", "args", "runs"),
    [
        ("otp_verify", {"code": "[DATE_1]"}, False),
        ("otp_verify", {"code": "[DOC_1]"}, False),
        (
            "customer_match",
            {"document_type": "NATIONAL_ID", "document_number": "[OTP_1]"},
            False,
        ),
        (
            "customer_match",
            {"document_type": "NATIONAL_ID", "document_number": "[DATE_1]"},
            False,
        ),
        ("otp_verify", {"code": "[OTP_1]"}, True),
        (
            "customer_match",
            {"document_type": "NATIONAL_ID", "document_number": "[DOC_1]"},
            True,
        ),
    ],
    ids=[
        "otp-as-date",
        "otp-as-doc",
        "doc-as-otp",
        "doc-as-date",
        "otp-as-otp",
        "doc-as-doc",
    ],
)
async def test_secrets_require_a_placeholder_of_the_right_kind(
    mock_services: Any, name: str, args: dict[str, Any], runs: bool
) -> None:
    banking = FakeBankingCore()
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
        [Step(tool_calls=[tool_call("call_1", name, args)]), Step(content="Ok.")]
    )
    context = new_context()

    # Every wrong-kind value below also satisfies the target argument's contract
    # pattern, so only the engine's kind check stops it, not local validation.
    result = await make_engine(llm).run_turn(
        context, "Mi cédula es 654321, nací el 15-03-1985 y mi código es 123456"
    )

    # The masker gave each value a placeholder of its own kind.
    assert context.placeholder_map == {
        "[DOC_1]": "654321",
        "[DATE_1]": "15-03-1985",
        "[OTP_1]": "123456",
    }
    outcome = result.metadata.tool_outcomes[0]
    assert outcome.executed is runs
    assert len(banking.requests) == (1 if runs else 0)
    if not runs:
        assert outcome.reason_code is not None
        assert outcome.reason_code.value == "INVALID_ARGUMENTS"


async def test_bare_otp_equal_to_an_earlier_document_still_gets_an_otp_placeholder(
    mock_services: Any,
) -> None:
    banking = FakeBankingCore()
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
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
            Step(tool_calls=[tool_call("call_2", "otp_send", {})]),
            Step(content="Te envié un código."),
            Step(tool_calls=[tool_call("call_3", "otp_verify", {"code": "[OTP_1]"})]),
            Step(content="Verificado."),
        ]
    )
    engine = make_engine(llm)
    context = new_context()

    # The customer's document number happens to equal the code sent later.
    await engine.run_turn(context, "Mi cédula es 482913")
    await engine.run_turn(context, "482913")

    assert context.placeholder_map == {"[DOC_1]": "482913", "[OTP_1]": "482913"}
    assert "482913" not in json.dumps(context.history)
    assert banking.calls_to("otp.verify")[0]["args"]["code"] == "482913"


async def test_code_typed_before_the_challenge_is_not_submitted(
    mock_services: Any,
) -> None:
    banking = FakeBankingCore()
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
        [
            # The customer already typed a code, before any challenge existed.
            Step(
                tool_calls=[
                    tool_call(
                        "call_1",
                        "customer_match",
                        {"document_type": "NATIONAL_ID", "document_number": "[DOC_1]"},
                    )
                ]
            ),
            Step(tool_calls=[tool_call("call_2", "otp_send", {})]),
            Step(tool_calls=[tool_call("call_3", "otp_verify", {"code": "[OTP_1]"})]),
            Step(content="Escribe el código que acabo de enviarte."),
            Step(tool_calls=[tool_call("call_4", "otp_verify", {"code": "[OTP_2]"})]),
            Step(content="Verificado."),
        ]
    )
    engine = make_engine(llm)
    context = new_context()

    first = await engine.run_turn(
        context, f"Mi cédula es {RAW_DOCUMENT} y mi código es 111111"
    )
    second = await engine.run_turn(context, "482913")

    stale = first.metadata.tool_outcomes[-1]
    assert (stale.tool, stale.executed) == ("otp.verify", False)
    assert stale.reason_code is not None
    assert stale.reason_code.value == "INVALID_ARGUMENTS"
    assert second.metadata.tool_outcomes[0].executed is True
    codes = [call["args"]["code"] for call in banking.calls_to("otp.verify")]
    assert codes == ["482913"]


async def test_resending_the_code_makes_the_previous_one_stale(
    mock_services: Any,
) -> None:
    wrong = {
        **OK_DATA["otp.verify"],
        "verified": False,
        "state": "OTP_PENDING",
        "receipt": receipt("otp.verify", "chal_abcdef01", "OTP_PENDING", "OTP_PENDING"),
    }
    banking = FakeBankingCore(data={"otp.verify": wrong})
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_1", "otp_send", {})]),
            Step(content="Te envié un código."),
            Step(tool_calls=[tool_call("call_2", "otp_verify", {"code": "[OTP_1]"})]),
            Step(content="Incorrecto. ¿Quieres que te envíe otro?"),
            # A resend, then the model tries the first code against the new one.
            Step(tool_calls=[tool_call("call_3", "otp_send", {})]),
            Step(tool_calls=[tool_call("call_4", "otp_verify", {"code": "[OTP_1]"})]),
            Step(content="Te envié uno nuevo."),
            Step(tool_calls=[tool_call("call_5", "otp_verify", {"code": "[OTP_2]"})]),
            Step(content="Incorrecto."),
        ]
    )
    engine = make_engine(llm)
    context = new_context()

    await engine.run_turn(context, "Quiero bloquear mi tarjeta")
    await engine.run_turn(context, "111111")
    resent = await engine.run_turn(context, "Envíame otro código")
    await engine.run_turn(context, "222222")

    assert [(o.tool, o.executed) for o in resent.metadata.tool_outcomes] == [
        ("otp.send", True),
        ("otp.verify", False),
    ]
    codes = [call["args"]["code"] for call in banking.calls_to("otp.verify")]
    assert codes == ["111111", "222222"]


async def test_retyping_the_same_code_after_the_challenge_makes_it_current(
    mock_services: Any,
) -> None:
    banking = FakeBankingCore()
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_1", "otp_send", {})]),
            Step(content="Te envié un código."),
            Step(tool_calls=[tool_call("call_2", "otp_verify", {"code": "[OTP_1]"})]),
            Step(content="Verificado."),
        ]
    )
    engine = make_engine(llm)
    context = new_context()

    # Typed before the challenge, then typed again after it: same placeholder.
    await engine.run_turn(context, "Mi código es 111111, envíame otro")
    await engine.run_turn(context, "111111")

    assert list(context.placeholder_map) == ["[OTP_1]"]
    assert [c["args"]["code"] for c in banking.calls_to("otp.verify")] == ["111111"]


def test_from_settings_wires_max_rounds_and_encoder_flag() -> None:
    enabled = TurnEngine.from_settings(
        Settings(max_tool_rounds=3, encoder_enabled=True)
    )
    disabled = TurnEngine.from_settings(Settings(encoder_enabled=False))

    assert enabled.max_tool_rounds == 3
    assert enabled.encoder is not None
    assert disabled.encoder is None


def test_tool_feedback_preserves_integer_amounts_and_masks_string_pii() -> None:
    engine = make_engine(ScriptedLLM([]))
    balance = ToolResult.model_validate(
        {
            "tool": "account.get_summary",
            "status": "ok",
            "data": {
                "accounts": [
                    {
                        "account_ref": "acct_abcd1234",
                        "account_type": "CHECKING",
                        "currency": "COP",
                        "available_balance_minor": 55000000,
                        "ledger_balance_minor": 56000000,
                        "status": "ACTIVE",
                    }
                ]
            },
        }
    )

    balance_feedback = json.loads(
        engine._tool_feedback("account_get_summary", balance, {})
    )
    account = balance_feedback["data"]["accounts"][0]
    assert account["available_balance_minor"] == 55000000
    assert account["ledger_balance_minor"] == 56000000

    knowledge = ToolResult.model_validate(
        {
            "tool": "kb.search",
            "status": "ok",
            "data": {
                "results": [
                    {
                        "article_id": "kb_contact",
                        "title": "Contact details",
                        "snippet": "Document 1020304050; phone +14155551234.",
                        "category": "support",
                        "score": 0.9,
                    }
                ]
            },
        }
    )
    knowledge_feedback = json.loads(engine._tool_feedback("kb_search", knowledge, {}))
    snippet = knowledge_feedback["data"]["results"][0]["snippet"]
    assert "1020304050" not in snippet
    assert "+14155551234" not in snippet
    assert "[DOC_" in snippet
    assert "[PHONE_" in snippet


@pytest.mark.asyncio
async def test_handoff_block_is_built_from_successful_result_only(
    mock_services: Any,
) -> None:
    model_text = "Model claims verified_facts are already confirmed."
    server_summary = {
        "verified_facts": {
            "verification_state": "VERIFIED",
            "customer_identified": True,
            "policy_flags": ["HANDOFF_REQUIRED"],
        },
        "actions_taken": [
            {
                "action": "card.block",
                "decision": "allowed",
                "reason_code": None,
                "audit_id": "aud_0001abcd",
            }
        ],
        "verification_method": "document_match_and_otp",
        "open_questions": [{"source": "model_unverified", "text": model_text}],
    }
    banking = FakeBankingCore(
        data={
            "handoff.create": {
                **OK_DATA["handoff.create"],
                "priority": "HIGH",
                "summary": server_summary,
            }
        }
    )
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
        [
            Step(
                tool_calls=[
                    tool_call(
                        "call_handoff",
                        "handoff_create",
                        {
                            "reason": "CUSTOMER_REQUEST",
                            "summary": model_text,
                            "priority": "LOW",
                            "department": "DISPUTES",
                        },
                    )
                ]
            ),
            Step(content=json.dumps({"blocks": [{"type": "handoff"}]})),
        ]
    )

    result = await make_engine(llm).run_turn(
        new_context(), "Please connect me with a person."
    )

    handoffs = [block for block in result.blocks if isinstance(block, HandoffBlock)]
    assert len(handoffs) == 1
    handoff = handoffs[0]
    assert handoff.handoff_id == "hnd_abcd1234"
    assert handoff.status.value == "QUEUED"
    assert handoff.department.value == "DISPUTES"
    assert handoff.priority.value == "HIGH"
    assert handoff.queue_position == 4
    assert handoff.receipt.action == "handoff.create"
    assert handoff.summary.verified_facts == server_summary["verified_facts"]
    assert handoff.summary.actions_taken == server_summary["actions_taken"]
    assert handoff.summary.verification_method == "document_match_and_otp"
    assert handoff.summary.open_questions[0].text == model_text
    assert model_text not in json.dumps(handoff.summary.verified_facts)
    assert result.metadata.dropped_block_types == ["handoff"]
    assert not any(
        isinstance(block, ReceiptBlock) and block.receipt.action == "handoff.create"
        for block in result.blocks
    )


@pytest.mark.asyncio
async def test_refused_handoff_does_not_produce_handoff_block(
    mock_services: Any,
) -> None:
    banking = FakeBankingCore(refuse={"handoff.create": "STATE_NOT_ALLOWED"})
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
        [
            Step(
                tool_calls=[
                    tool_call(
                        "call_handoff",
                        "handoff_create",
                        {
                            "reason": "CUSTOMER_REQUEST",
                            "summary": json.dumps(
                                {
                                    "verified_facts": (
                                        "Customer requested a human agent."
                                    ),
                                    "actions_taken": "No handoff was created.",
                                    "verification_method": "Not verified.",
                                    "open_questions": "What support is needed?",
                                }
                            ),
                        },
                    )
                ]
            ),
            Step(content="A human handoff could not be created."),
        ]
    )

    result = await make_engine(llm).run_turn(
        new_context(), "Please connect me with a person."
    )

    assert not any(isinstance(block, HandoffBlock) for block in result.blocks)


@pytest.mark.asyncio
async def test_malformed_handoff_result_does_not_create_block(
    mock_services: Any,
) -> None:
    malformed = {
        **OK_DATA["handoff.create"],
        "summary": {"verified_facts": {}},
    }
    banking = FakeBankingCore(data={"handoff.create": malformed})
    route = mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM(
        [
            Step(
                tool_calls=[
                    tool_call(
                        "call_handoff",
                        "handoff_create",
                        {
                            "reason": "CUSTOMER_REQUEST",
                            "summary": "Model-requested escalation summary.",
                            "priority": "LOW",
                            "department": "DISPUTES",
                        },
                    )
                ]
            ),
            Step(content="Escalation request submitted."),
        ]
    )

    result = await make_engine(llm).run_turn(
        new_context(), "Please connect me with a person."
    )

    assert route.call_count == 1
    assert not any(isinstance(block, HandoffBlock) for block in result.blocks)


OPENING_FLOW = FlowHint(
    state="ANONYMOUS",
    next=["customer.match"],
    allowed=["customer.match", "handoff.create", "kb.search"],
    enabled=[
        "customer.match",
        "otp.send",
        "otp.verify",
        "card.list",
        "transaction.list_recent",
        "card.block",
        "handoff.create",
        "kb.search",
    ],
)


def _system_lines(call: dict[str, Any]) -> list[str]:
    return [m["content"] for m in call["messages"] if m["role"] == "system"]


async def test_the_first_completion_reads_where_the_session_starts(
    mock_services: Any,
) -> None:
    """ADR-0016 amendment 2026-10-02: the hint of session creation, until a result."""
    banking = FakeBankingCore(refuse={"handoff.create": "POLICY_BLOCKED"})
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    dispute = {"reason": "DISPUTE_CLAIM", "summary": "Unrecognized purchase."}
    llm = ScriptedLLM(
        [
            Step(tool_calls=[tool_call("call_1", "handoff_create", dispute)]),
            Step(content="¿Me compartes tu número de documento?"),
        ]
    )
    context = ConversationContext(
        session_id=SESSION_ID,
        language="es",
        enabled_tools=list(OPENING_FLOW.enabled),
        opening_flow=OPENING_FLOW,
    )

    await make_engine(llm).run_turn(
        context, "he detectado una compra que no hice con mi tarjeta"
    )

    first, second = llm.calls
    opening = [line for line in _system_lines(first) if "banking-core flow" in line]
    assert opening == [
        "banking-core flow (advisory and internal, never for the customer; "
        "banking-core decides every call): the session is ANONYMOUS; the step that "
        "moves it forward is `customer_match`, once the customer has given what it "
        "needs."
    ]
    # Only what the configuration enables is offered, from the first completion.
    offered = {tool["function"]["name"] for tool in first["tools"]}
    assert "account_get_summary" not in offered
    assert "customer_match" in offered
    # The refusal is in the history now: the hint travels in the results.
    assert not any("banking-core flow" in line for line in _system_lines(second))


async def test_without_an_opening_hint_the_first_completion_is_as_before(
    mock_services: Any,
) -> None:
    mock_services.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )
    llm = ScriptedLLM([Step(content="Hola, ¿en qué te ayudo?")])

    await make_engine(llm).run_turn(new_context(), "hola")

    assert not any("banking-core flow" in line for line in _system_lines(llm.calls[0]))
    offered = {tool["function"]["name"] for tool in llm.calls[0]["tools"]}
    assert "account_get_summary" in offered


# ---------------------------------------------- the fixed identity request


def anonymous_context(language: str = "es") -> ConversationContext:
    return ConversationContext(
        session_id=SESSION_ID,
        language=language,
        enabled_tools=list(OPENING_FLOW.enabled),
        opening_flow=OPENING_FLOW,
    )


NO_DOCUMENT_MATCH = tool_call(
    "call_1", "customer_match", {"document_type": "NATIONAL_ID"}
)
BLOCK = tool_call(
    "call_1", "card_block", {"card_ref": "card_ab12cd34", "reason": "STOLEN"}
)
RECENT = tool_call("call_1", "transaction_list_recent", {})


def identity_request(topic: str, lang: str = "es") -> str:
    return f"{IDENTITY_REQUEST_OPENINGS[topic][lang]} {IDENTITY_REQUEST_ASK[lang]}"


@pytest.mark.parametrize(
    ("call", "refuse", "topic"),
    [
        (NO_DOCUMENT_MATCH, {}, "neutral"),
        (BLOCK, {"card.block": "STATE_NOT_ALLOWED"}, "card_block"),
    ],
    ids=["match-without-document", "block-while-anonymous"],
)
async def test_a_tool_before_any_document_gets_the_fixed_identity_request(
    mock_services: Any, call: dict[str, Any], refuse: dict[str, str], topic: str
) -> None:
    """Nothing was checked: the reply asks for the document, it does not relay
    the refusal (which the model read as a failed verification)."""
    banking = FakeBankingCore(refuse=refuse)
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    llm = ScriptedLLM([Step(tool_calls=[call])])
    context = anonymous_context()

    result = await make_engine(llm).run_turn(
        context, "quiero bloquear mi tarjeta porque no reconozco los ultimos pagos"
    )

    assert result.blocks == [TextBlock(text=identity_request(topic))]
    assert result.metadata.identity_requested is True
    assert len(llm.calls) == 1
    assert [r["body"]["tool"] for r in banking.requests] == (
        ["card.block"] if refuse else []
    )
    assert context.history[-1] == {
        "role": "assistant",
        "content": identity_request(topic),
    }
    assert_no_dangling_tool_calls(context.history)


async def test_the_identity_request_opens_with_the_request_the_model_reached_for(
    mock_services: Any,
) -> None:
    """Asking to see transfers is not answered with card protection."""
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(
        side_effect=FakeBankingCore(
            refuse={"transaction.list_recent": "STATE_NOT_ALLOWED"}
        )
    )
    _mock_encoder(mock_services)
    llm = ScriptedLLM([Step(tool_calls=[NO_DOCUMENT_MATCH, RECENT])])

    result = await make_engine(llm).run_turn(
        anonymous_context(), "quiero ver las trasferencias ultimas"
    )

    assert result.blocks == [TextBlock(text=identity_request("transactions"))]
    assert "tarjeta" not in result.blocks[0].text


async def test_the_identity_request_speaks_the_customer_language(
    mock_services: Any,
) -> None:
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(
        side_effect=FakeBankingCore(refuse={"card.block": "STATE_NOT_ALLOWED"})
    )
    _mock_encoder(mock_services)
    llm = ScriptedLLM([Step(tool_calls=[BLOCK])])

    result = await make_engine(llm).run_turn(
        anonymous_context("pt"), "quero bloquear meu cartão"
    )

    assert result.blocks == [TextBlock(text=identity_request("card_block", "pt"))]


async def test_after_a_document_a_refusal_is_explained_by_the_model(
    mock_services: Any,
) -> None:
    banking = FakeBankingCore(refuse={"card.block": "STATE_NOT_ALLOWED"})
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    _mock_encoder(mock_services)
    reply = "Primero te envío un código para confirmar que eres tú."
    llm = ScriptedLLM([Step(tool_calls=[BLOCK]), Step(content=reply)])
    context = anonymous_context()

    result = await make_engine(llm).run_turn(
        context, f"Bloquea mi tarjeta, mi cédula es {RAW_DOCUMENT}"
    )

    assert "[DOC_1]" in context.placeholder_map
    assert result.blocks == [TextBlock(text=reply)]
    assert result.metadata.identity_requested is False


async def test_without_a_known_anonymous_state_the_model_explains_the_refusal(
    mock_services: Any,
) -> None:
    """No flow hint from banking-core (or one in another state, below): the engine
    cannot tell that nothing was asked yet, so the model answers as before."""
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(
        side_effect=FakeBankingCore(refuse={"card.block": "STATE_NOT_ALLOWED"})
    )
    _mock_encoder(mock_services)
    llm = ScriptedLLM([Step(tool_calls=[BLOCK]), Step(content="No puedo aún.")])

    result = await make_engine(llm).run_turn(new_context(), "Bloquea mi tarjeta")

    assert result.blocks == [TextBlock(text="No puedo aún.")]
    assert result.metadata.identity_requested is False


async def test_a_refusal_from_a_handed_off_session_is_not_an_identity_request(
    mock_services: Any,
) -> None:
    def handed_off(request: httpx.Request) -> httpx.Response:
        tool = json.loads(request.content)["tool"]
        return httpx.Response(
            200,
            json={
                "tool": tool,
                "status": "refused",
                "reason_code": "STATE_NOT_ALLOWED",
                "data": None,
                "flow": {"state": "HANDED_OFF", "allowed": ["handoff.create"]},
            },
        )

    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=handed_off)
    _mock_encoder(mock_services)
    reply = "Un agente ya está revisando tu caso."
    llm = ScriptedLLM([Step(tool_calls=[BLOCK]), Step(content=reply)])

    result = await make_engine(llm).run_turn(anonymous_context(), "Bloquéala ya")

    assert result.blocks == [TextBlock(text=reply)]
    assert result.metadata.identity_requested is False


async def test_a_round_with_a_tool_that_ran_is_answered_by_the_model(
    mock_services: Any,
) -> None:
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(
        side_effect=FakeBankingCore()
    )
    _mock_encoder(mock_services)
    search = tool_call("call_2", "kb_search", {"query": "bloqueo de tarjeta"})
    reply = "Puedo ayudarte a bloquearla. ¿Cuál es tu documento?"
    llm = ScriptedLLM(
        [Step(tool_calls=[NO_DOCUMENT_MATCH, search]), Step(content=reply)]
    )

    result = await make_engine(llm).run_turn(
        anonymous_context(), "¿cómo bloqueo mi tarjeta?"
    )

    assert result.blocks == [TextBlock(text=reply)]
    assert result.metadata.identity_requested is False
