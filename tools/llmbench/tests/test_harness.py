"""The harness end to end with the oracle: real engine, sandbox bank, no server."""

from contracts.envelope import VerificationState
from llmbench.harness import Conversation
from llmbench.oracle import OracleLLM, OracleTurn, Resolver
from llmbench.provider import BenchProvider
from llmbench.sandbox import BankSetup, SandboxBank


def oracle(bank: SandboxBank, turn: OracleTurn) -> BenchProvider:
    return BenchProvider(OracleLLM(turn, Resolver(bank)), by_oracle=True)


async def test_oracle_walks_the_lost_card_flow():
    bank = SandboxBank(BankSetup(customer="demo_es"))
    conversation = Conversation(bank, "es")

    first = await conversation.turn(
        "Perdí mi tarjeta. Mi cédula es 1020304050.",
        oracle(
            bank,
            OracleTurn(
                calls=[
                    (
                        "customer.match",
                        {
                            "document_type": "NATIONAL_ID",
                            "document_number": "{{ph:DOC}}",
                        },
                    ),
                    ("otp.send", {}),
                ],
                reply="Te envié un código. ¿Me lo compartes?",
            ),
        ),
    )
    assert first.error is None
    assert first.state_after is VerificationState.OTP_PENDING
    # The model saw the placeholder, never the document.
    sent = first.llm_calls[0]
    assert sent.tool_calls[0]["function"]["arguments"].count("[DOC_1]") == 1

    second = await conversation.turn(
        "{{otp}}",
        oracle(
            bank,
            OracleTurn(
                calls=[
                    ("otp.verify", {"code": "{{ph:OTP}}"}),
                    ("card.block", {"card_ref": "{{card}}", "reason": "LOST"}),
                ],
                reply="Tu tarjeta quedó bloqueada.",
            ),
        ),
    )
    assert second.error is None
    assert [c.tool for c in second.bank_calls] == ["otp.verify", "card.block"]
    assert second.state_after is VerificationState.VERIFIED
    assert [c.card_ref for c in bank.cards_blocked_since_start()] == ["card_demo_es"]
    assert any(block.type == "receipt" for block in second.result.blocks)
    assert "1020304050" not in str(conversation.context.history)


async def test_required_handoff_is_created_by_the_engine():
    bank = SandboxBank(
        BankSetup(
            customer="demo_es", thresholds_minor={"COP": 1000}, amount_mode="block"
        )
    )
    conversation = Conversation(bank, "es")
    await conversation.turn(
        "No reconozco un cargo. Cédula 1020304050.",
        oracle(
            bank,
            OracleTurn(
                calls=[
                    (
                        "customer.match",
                        {
                            "document_type": "NATIONAL_ID",
                            "document_number": "{{ph:DOC}}",
                        },
                    ),
                    ("otp.send", {}),
                ],
                reply="¿Me compartes el código?",
            ),
        ),
    )
    record = await conversation.turn(
        "{{otp}}",
        oracle(
            bank,
            OracleTurn(
                calls=[
                    ("otp.verify", {"code": "{{ph:OTP}}"}),
                    (
                        "card.block",
                        {
                            "card_ref": "{{card}}",
                            "reason": "UNRECOGNIZED_CHARGE",
                            "transaction_id": "{{tx:Global Electronics}}",
                        },
                    ),
                ],
                reply="Bloqueé la tarjeta.",
            ),
        ),
    )
    assert [c.tool for c in record.bank_calls] == [
        "otp.verify",
        "card.block",
        "handoff.create",
    ]
    assert record.state_after is VerificationState.HANDED_OFF


async def test_routing_offers_only_what_the_state_allows():
    bank = SandboxBank(BankSetup(customer="demo_es"))
    conversation = Conversation(bank, "es")
    llm = BenchProvider(
        OracleLLM(OracleTurn(reply="Hola, ¿en qué te ayudo?"), Resolver(bank)),
        llm_names=conversation.llm_names,
        allowed_tools=conversation.allowed_tools,
    )
    record = await conversation.turn("Hola", llm)
    assert record.reply_text == "Hola, ¿en qué te ayudo?"
    # ANONYMOUS: customer.match, handoff.create and kb.search.
    assert record.llm_calls[0].tools_offered == 3


def test_live_provider_ignores_the_environment(monkeypatch):
    from llmbench.provider import live_provider

    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    provider = live_provider("openai/qwen3-1.7b", "http://127.0.0.1:8090/v1")
    assert provider.mode == "live"
    assert provider.model == "openai/qwen3-1.7b"
    assert provider.base_url == "http://127.0.0.1:8090/v1"
    assert provider.reasoning_effort is None
    assert provider.record is False
