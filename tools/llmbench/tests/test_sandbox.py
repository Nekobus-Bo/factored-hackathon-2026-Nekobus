"""SandboxBank: banking-core's decisions over in-memory fixtures."""

import pytest
from contracts import ReasonCode, ToolCall, ToolResultStatus
from contracts.envelope import VerificationState
from contracts.tools.card_list import CardStatus
from llmbench.sandbox import BankSetup, ExtraCard, SandboxBank

DOC_ES = {"document_type": "NATIONAL_ID", "document_number": "1020304050"}


def call(tool: str, key: str | None = None, **args) -> ToolCall:
    return ToolCall(tool=tool, args=args, idempotency_key=key)


async def verified(bank: SandboxBank, doc: dict = DOC_ES) -> str:
    session = bank.create_session()
    assert (await bank.call_tool(session, call("customer.match", **doc))).data == {
        "matched": True
    }
    await bank.call_tool(session, call("otp.send", "key-send-1"))
    code = bank.otp_code(session)
    result = await bank.call_tool(
        session, call("otp.verify", "key-verify-1", code=code)
    )
    assert result.data["verified"] is True
    assert bank.state(session) is VerificationState.VERIFIED
    return session


async def unrecognized_tx(bank: SandboxBank, session: str) -> dict:
    listing = await bank.call_tool(session, call("transaction.list_recent"))
    return next(
        t
        for t in listing.data["transactions"]
        if t["merchant_name"] == "Global Electronics Megastore"
    )


async def test_customer_data_is_refused_before_verification():
    bank = SandboxBank(BankSetup(customer="demo_es"))
    session = bank.create_session()
    for tool in ("card.list", "transaction.list_recent"):
        result = await bank.call_tool(session, call(tool))
        assert result.status is ToolResultStatus.REFUSED
        assert result.reason_code is ReasonCode.STATE_NOT_ALLOWED
    result = await bank.call_tool(
        session,
        call("card.block", "key-block-1", card_ref="card_demo_es", reason="LOST"),
    )
    assert result.reason_code is ReasonCode.STATE_NOT_ALLOWED


async def test_unknown_document_does_not_match():
    bank = SandboxBank(BankSetup(customer="demo_unregistered"))
    session = bank.create_session()
    result = await bank.call_tool(
        session,
        call("customer.match", document_type="NATIONAL_ID", document_number="99999999"),
    )
    assert result.data == {"matched": False}
    assert bank.state(session) is VerificationState.ANONYMOUS


async def test_three_wrong_codes_lock_the_session():
    bank = SandboxBank(BankSetup(customer="demo_es"))
    session = bank.create_session()
    await bank.call_tool(session, call("customer.match", **DOC_ES))
    await bank.call_tool(session, call("otp.send", "key-send-1"))
    wrong = "000000" if bank.otp_code(session) != "000000" else "111111"
    for attempt in range(3):
        result = await bank.call_tool(
            session, call("otp.verify", f"key-verify-{attempt}", code=wrong)
        )
        assert result.data["verified"] is False
    assert bank.state(session) is VerificationState.LOCKED
    assert result.data["attempts_remaining"] == 0


async def test_no_channel_refuses_the_otp():
    bank = SandboxBank(BankSetup(customer="demo_es", otp_channel_present=False))
    session = bank.create_session()
    await bank.call_tool(session, call("customer.match", **DOC_ES))
    result = await bank.call_tool(session, call("otp.send", "key-send-1"))
    assert result.reason_code is ReasonCode.POLICY_BLOCKED
    assert bank.state(session) is VerificationState.IDENTIFIED


@pytest.mark.parametrize(
    ("thresholds", "mode", "level"),
    [
        (None, "flag", "NONE"),
        ({"COP": 1000}, "flag", "RECOMMENDED"),
        ({"COP": 1000}, "block", "REQUIRED"),
    ],
)
async def test_amount_policy_reads_the_linked_transaction(thresholds, mode, level):
    bank = SandboxBank(
        BankSetup(customer="demo_es", thresholds_minor=thresholds, amount_mode=mode)
    )
    session = await verified(bank)
    tx = await unrecognized_tx(bank, session)
    result = await bank.call_tool(
        session,
        call(
            "card.block",
            "key-block-1",
            card_ref=tx["card_ref"],
            reason="UNRECOGNIZED_CHARGE",
            transaction_id=tx["transaction_id"],
        ),
    )
    assert result.status is ToolResultStatus.OK
    assert result.data["handoff_requirement"]["level"] == level
    assert [c.card_ref for c in bank.cards_blocked_since_start()] == ["card_demo_es"]


async def test_dispute_without_a_transaction_fails_safe_to_required():
    bank = SandboxBank(BankSetup(customer="demo_es"))
    session = await verified(bank)
    result = await bank.call_tool(
        session,
        call(
            "card.block",
            "key-block-1",
            card_ref="card_demo_es",
            reason="UNRECOGNIZED_CHARGE",
        ),
    )
    assert result.data["handoff_requirement"]["level"] == "REQUIRED"


async def test_someone_elses_transaction_or_card_is_not_resolved():
    bank = SandboxBank(BankSetup(customer="demo_es"))
    other = SandboxBank(BankSetup(customer="demo_pt"))
    foreign_tx = await unrecognized_tx(
        other,
        await verified(
            other, {"document_type": "NATIONAL_ID", "document_number": "12345678900"}
        ),
    )
    session = await verified(bank)
    result = await bank.call_tool(
        session,
        call(
            "card.block",
            "key-block-1",
            card_ref="card_demo_es",
            reason="UNRECOGNIZED_CHARGE",
            transaction_id=foreign_tx["transaction_id"],
        ),
    )
    assert result.reason_code is ReasonCode.INVALID_ARGUMENTS
    result = await bank.call_tool(
        session,
        call("card.block", "key-block-2", card_ref="card_demo_pt", reason="LOST"),
    )
    assert result.status is ToolResultStatus.ERROR
    assert bank.cards_blocked_since_start() == []


async def test_same_key_replays_and_a_reused_key_is_refused():
    bank = SandboxBank(BankSetup(customer="demo_es"))
    session = await verified(bank)
    block = call("card.block", "key-block-1", card_ref="card_demo_es", reason="LOST")
    first = await bank.call_tool(session, block)
    again = await bank.call_tool(session, block)
    assert again == first
    assert bank.calls(session)[-1].replayed is True
    reused = await bank.call_tool(
        session,
        call("card.block", "key-block-1", card_ref="card_demo_es", reason="STOLEN"),
    )
    assert reused.reason_code is ReasonCode.INVALID_ARGUMENTS


async def test_seed_tool_policy_disables_account_summary():
    bank = SandboxBank(BankSetup(customer="demo_es"))
    session = await verified(bank)
    result = await bank.call_tool(session, call("account.get_summary"))
    assert result.reason_code is ReasonCode.STATE_NOT_ALLOWED

    enabled = SandboxBank(
        BankSetup(customer="demo_es", enabled_tools=frozenset({"account.get_summary"}))
    )
    session = await verified(enabled)
    result = await enabled.call_tool(session, call("account.get_summary"))
    assert result.status is ToolResultStatus.OK
    assert result.data["accounts"][0]["currency"] == "COP"


async def test_handoff_works_anonymous_and_is_one_per_session():
    bank = SandboxBank(BankSetup(customer="demo_es"))
    session = bank.create_session()
    args = {
        "reason": "CUSTOMER_REQUEST",
        "summary": "Customer asks for a person",
        "department": "CUSTOMER_SUPPORT",
    }
    first = await bank.call_tool(session, call("handoff.create", "key-hand-1", **args))
    assert first.status is ToolResultStatus.OK
    assert bank.state(session) is VerificationState.HANDED_OFF
    assert set(first.data["summary"]) == {
        "verified_facts",
        "actions_taken",
        "verification_method",
        "open_questions",
    }
    second = await bank.call_tool(session, call("handoff.create", "key-hand-2", **args))
    assert second.data["handoff_id"] == first.data["handoff_id"]


async def test_required_requirement_routes_and_raises_the_handoff():
    bank = SandboxBank(
        BankSetup(
            customer="demo_es", thresholds_minor={"COP": 1000}, amount_mode="block"
        )
    )
    session = await verified(bank)
    tx = await unrecognized_tx(bank, session)
    await bank.call_tool(
        session,
        call(
            "card.block",
            "key-block-1",
            card_ref=tx["card_ref"],
            reason="UNRECOGNIZED_CHARGE",
            transaction_id=tx["transaction_id"],
        ),
    )
    result = await bank.call_tool(
        session,
        call(
            "handoff.create",
            "key-hand-1",
            reason="DISPUTE_CLAIM",
            summary="Dispute of the electronics charge",
            priority="LOW",
            department="CUSTOMER_SUPPORT",
            transaction_id=tx["transaction_id"],
        ),
    )
    assert result.data["department"] == "DISPUTES"
    assert result.data["priority"] == "URGENT"
    facts = result.data["summary"]["verified_facts"]
    assert facts["disputed_transaction"]["merchant"] == "Global Electronics Megastore"


async def test_setup_card_status_and_extra_cards():
    bank = SandboxBank(
        BankSetup(
            customer="demo_es",
            card_status=CardStatus.BLOCKED,
            extra_cards=[ExtraCard(card_ref="card_extra_es", pan_last4="7788")],
        )
    )
    session = await verified(bank)
    listing = await bank.call_tool(session, call("card.list"))
    cards = {c["card_ref"]: c for c in listing.data["cards"]}
    assert cards["card_demo_es"]["status"] == "BLOCKED"
    assert cards["card_extra_es"]["card_type"] == "CREDIT"


async def test_fault_tool_down_answers_internal_error():
    bank = SandboxBank(BankSetup(customer="demo_es", fault="tool_down"))
    session = bank.create_session()
    result = await bank.call_tool(session, call("customer.match", **DOC_ES))
    assert result.status is ToolResultStatus.ERROR
    assert result.reason_code is ReasonCode.INTERNAL_ERROR
