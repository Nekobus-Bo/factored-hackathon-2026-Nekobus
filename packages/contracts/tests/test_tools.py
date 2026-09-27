"""Tests proving every tool input validates good input and rejects bad input."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from contracts.envelope import Receipt, ResourceState, VerificationState
from contracts.tools import (
    AccountGetSummaryInput,
    AccountGetSummaryOutput,
    AccountStatus,
    AccountSummaryItem,
    AccountType,
    BlockReason,
    CardBlockInput,
    CardBlockOutput,
    CardItem,
    CardListInput,
    CardListOutput,
    CardStatus,
    CardStatusFilter,
    CardType,
    CustomerMatchInput,
    CustomerMatchOutput,
    Department,
    DocumentDecision,
    DocumentType,
    HandoffCreateInput,
    HandoffCreateOutput,
    HandoffPriority,
    HandoffReason,
    HandoffStatus,
    IdentityVerifyDocumentInput,
    IdentityVerifyDocumentOutput,
    KbSearchInput,
    KbSearchOutput,
    KbSearchResultItem,
    OtpChannel,
    OtpSendInput,
    OtpSendOutput,
    OtpVerifyInput,
    OtpVerifyOutput,
    TransactionItem,
    TransactionListRecentInput,
    TransactionListRecentOutput,
    TransactionStatus,
)


@pytest.fixture
def sample_receipt() -> Receipt:
    return Receipt(
        action="test.action",
        target_masked="**** 1234",
        state_before=ResourceState.ACTIVE,
        state_after=ResourceState.BLOCKED,
        verified_at=datetime.now(timezone.utc),
        audit_id="audit-uuid-12345678",
    )


# 1. customer.match
def test_customer_match_good_input():
    valid = CustomerMatchInput(
        document_type=DocumentType.NATIONAL_ID,
        document_number="1020304050",
        birth_date=date(1990, 5, 20),
    )
    assert valid.document_type == DocumentType.NATIONAL_ID
    assert valid.document_number == "1020304050"

    valid_no_dob = CustomerMatchInput(
        document_type=DocumentType.PASSPORT,
        document_number="PA123456",
    )
    assert valid_no_dob.birth_date is None


def test_customer_match_bad_input():
    with pytest.raises(ValidationError):
        CustomerMatchInput(
            document_type=DocumentType.NATIONAL_ID,
            document_number="12",
        )

    with pytest.raises(ValidationError):
        CustomerMatchInput(
            document_type=DocumentType.NATIONAL_ID,
            document_number="12345@!#$",
        )

    with pytest.raises(ValidationError):
        CustomerMatchInput(
            document_type=DocumentType.NATIONAL_ID,
            document_number="1020304050",
            extra_field="malicious",  # type: ignore[call-arg]
        )


def test_customer_match_output():
    out = CustomerMatchOutput(matched=True)
    assert out.matched is True
    out_false = CustomerMatchOutput(matched=False)
    assert out_false.matched is False


# 2. otp.send
def test_otp_send_good_input():
    """otp.send takes empty input; channel and destination are strictly resolved server-side."""
    inp = OtpSendInput()
    assert inp.model_dump() == {}


def test_otp_send_bad_input():
    """otp.send strictly rejects channel, destination, or extra fields from the model."""
    with pytest.raises(ValidationError):
        OtpSendInput(channel="EMAIL")  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        OtpSendInput(channel="WHATSAPP")  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        OtpSendInput(phone_number="+573001234567")  # type: ignore[call-arg]


def test_otp_send_output():
    receipt = Receipt(
        action="otp.send",
        target_masked="m***@example.com",
        state_before=ResourceState.NONE,
        state_after=ResourceState.ISSUED,
        verified_at=datetime.now(timezone.utc),
        audit_id="audit-uuid-12345678",
    )
    # Test all 5 supported channels
    channels = [
        (OtpChannel.EMAIL, "m***@example.com"),
        (OtpChannel.SMS, "+57 300 *** 5678"),
        (OtpChannel.WHATSAPP, "+57 300 *** 5678"),
        (OtpChannel.TELEGRAM, "@m***user"),
        (OtpChannel.SIMULATED, "simulated"),
    ]
    for ch, dest in channels:
        out = OtpSendOutput(
            sent=True,
            challenge_id="chal-token-12345678",
            channel=ch,
            destination_masked=dest,
            expires_in_seconds=300,
            receipt=receipt,
        )
        assert out.sent is True
        assert out.channel == ch
        assert out.destination_masked == dest
        assert out.challenge_id == "chal-token-12345678"
        assert out.receipt.state_after == ResourceState.ISSUED


def test_otp_send_output_destination_masked_rejects_unmasked_pii(sample_receipt: Receipt):
    """Reviewer Probes: destination_masked strictly rejects unmasked PII
    and non-literal simulated values."""
    unmasked_probes = [
        "juan.perez@bank.com",
        "+57 300 123 4567",
        "simulated juan.perez@bank.com +573001234567",
    ]
    for bad_dest in unmasked_probes:
        with pytest.raises(ValidationError):
            OtpSendOutput(
                sent=True,
                challenge_id="chal-token-12345678",
                channel=OtpChannel.EMAIL,
                destination_masked=bad_dest,
                expires_in_seconds=300,
                receipt=sample_receipt,
            )


# 3. otp.verify
def test_otp_verify_good_input():
    inp = OtpVerifyInput(code="123456")
    assert inp.code == "123456"


def test_otp_verify_bad_input():
    with pytest.raises(ValidationError):
        OtpVerifyInput(code="12345")

    with pytest.raises(ValidationError):
        OtpVerifyInput(code="1234567")

    with pytest.raises(ValidationError):
        OtpVerifyInput(code="12a456")


def test_otp_verify_output():
    receipt = Receipt(
        action="otp.verify",
        target_masked="chal-***-1234",
        state_before=ResourceState.OTP_PENDING,
        state_after=ResourceState.VERIFIED,
        verified_at=datetime.now(timezone.utc),
        audit_id="audit-uuid-12345678",
    )
    out = OtpVerifyOutput(
        verified=True,
        state=VerificationState.VERIFIED,
        attempts_remaining=3,
        receipt=receipt,
    )
    assert out.verified is True
    assert out.state == VerificationState.VERIFIED
    assert out.receipt.state_after == ResourceState.VERIFIED


# 4. identity.verify_document
def test_identity_verify_document_good_input():
    inp = IdentityVerifyDocumentInput(
        document_type=DocumentType.NATIONAL_ID,
        document_front_ref="doc-front-ref-12345",
        document_back_ref="doc-back-ref-12345",
    )
    assert inp.document_front_ref == "doc-front-ref-12345"


def test_identity_verify_document_bad_input():
    with pytest.raises(ValidationError):
        IdentityVerifyDocumentInput(
            document_type=DocumentType.NATIONAL_ID,
            document_front_ref="short",
        )

    with pytest.raises(ValidationError):
        IdentityVerifyDocumentInput(
            document_type=DocumentType.NATIONAL_ID,
            document_front_ref="doc/front/ref invalid!",
        )


def test_identity_verify_document_output():
    out = IdentityVerifyDocumentOutput(
        decision=DocumentDecision.APPROVED,
        score=0.98,
        reasons=["LIVENESS_PASSED", "SECURITY_FEATURES_VALID"],
    )
    assert out.decision == DocumentDecision.APPROVED
    assert out.score == 0.98


# 5. card.list
def test_card_list_good_input():
    inp = CardListInput()
    assert inp.status_filter == CardStatusFilter.ALL


def test_card_list_bad_input():
    with pytest.raises(ValidationError):
        CardListInput(status_filter="INVALID_FILTER")  # type: ignore[arg-type]


def test_card_list_output():
    item = CardItem(
        card_ref="card-token-12345678",
        masked_pan="**** **** **** 1234",
        card_type=CardType.DEBIT,
        status=CardStatus.ACTIVE,
        expiry_month=12,
        expiry_year=2028,
    )
    out = CardListOutput(cards=[item])
    assert len(out.cards) == 1
    assert out.cards[0].card_ref == "card-token-12345678"

    # Expiry is optional: sources without it return None, never a fabricated date.
    no_expiry = CardItem(
        card_ref="card-token-12345678",
        masked_pan="**** **** **** 1234",
        card_type=CardType.CREDIT,
        status=CardStatus.BLOCKED,
    )
    assert no_expiry.expiry_month is None
    assert no_expiry.expiry_year is None
    with pytest.raises(ValidationError):
        CardItem(
            card_ref="card-token-12345678",
            masked_pan="**** **** **** 1234",
            card_type=CardType.DEBIT,
            status=CardStatus.ACTIVE,
            expiry_month=13,
        )

    with pytest.raises(ValidationError):
        CardItem(
            card_ref="card-token-12345678",
            masked_pan="4111111111111234",
            card_type=CardType.DEBIT,
            status=CardStatus.ACTIVE,
            expiry_month=12,
            expiry_year=2028,
        )


# 6. transaction.list_recent
def test_transaction_list_recent_good_input():
    inp = TransactionListRecentInput(limit=25)
    assert inp.limit == 25
    assert inp.card_ref is None


def test_transaction_list_recent_bad_input():
    with pytest.raises(ValidationError):
        TransactionListRecentInput(limit=0)

    with pytest.raises(ValidationError):
        TransactionListRecentInput(limit=51)


def test_transaction_list_recent_output():
    tx = TransactionItem(
        transaction_id="tx-ref-987654321",
        card_ref="card-ref-token-1234",
        amount_minor=15050,  # Minor units
        currency="COP",
        merchant_name="Supermercado Central",
        merchant_category="GROCERY",
        posted_at=datetime.now(timezone.utc),
        status=TransactionStatus.SETTLED,
        is_disputable=True,
    )
    out = TransactionListRecentOutput(transactions=[tx])
    assert len(out.transactions) == 1
    assert out.transactions[0].amount_minor == 15050


# 7. account.get_summary
def test_account_get_summary_good_input():
    inp = AccountGetSummaryInput()
    assert inp.include_balances is True


def test_account_get_summary_bad_input():
    with pytest.raises(ValidationError):
        AccountGetSummaryInput(target_account="12345")  # type: ignore[call-arg]


def test_account_get_summary_output():
    acc = AccountSummaryItem(
        account_ref="acc-ref-token-9988",
        account_type=AccountType.CHECKING,
        currency="USD",
        available_balance_minor=250000,  # Minor units ($2500.00)
        ledger_balance_minor=250000,
        status=AccountStatus.ACTIVE,
    )
    out = AccountGetSummaryOutput(accounts=[acc])
    assert len(out.accounts) == 1
    assert out.accounts[0].available_balance_minor == 250000


# 8. card.block
def test_card_block_good_input():
    inp = CardBlockInput(
        card_ref="card-ref-token-87654321",
        reason=BlockReason.SUSPICIOUS_ACTIVITY,
    )
    assert inp.card_ref == "card-ref-token-87654321"
    assert inp.reason == BlockReason.SUSPICIOUS_ACTIVITY


def test_card_block_bad_input():
    # Short card_ref
    with pytest.raises(ValidationError):
        CardBlockInput(
            card_ref="short",
            reason=BlockReason.LOST,
        )

    # Free text notes strictly rejected (removed to avoid PII vector)
    with pytest.raises(ValidationError):
        CardBlockInput(
            card_ref="card-ref-token-87654321",
            reason=BlockReason.STOLEN,
            notes="Customer reported fraud",  # type: ignore[call-arg]
        )


def test_card_block_output():
    receipt = Receipt(
        action="card.block",
        target_masked="**** **** **** 4321",
        state_before=ResourceState.ACTIVE,
        state_after=ResourceState.BLOCKED,
        verified_at=datetime.now(timezone.utc),
        audit_id="audit-log-ref-uuid-12345",
    )
    out = CardBlockOutput(
        card_ref="card-ref-token-87654321",
        status=CardStatus.BLOCKED,
        receipt=receipt,
    )
    assert out.status == CardStatus.BLOCKED
    assert out.receipt.state_after == ResourceState.BLOCKED


# 9. handoff.create
def test_handoff_create_good_input():
    inp = HandoffCreateInput(
        reason=HandoffReason.DISPUTE_CLAIM,
        summary="Customer confirmed unrecognized transaction tx-123; card blocked.",
        priority=HandoffPriority.HIGH,
        department=Department.FRAUD_OPERATIONS,
    )
    assert inp.reason == HandoffReason.DISPUTE_CLAIM
    assert inp.priority == HandoffPriority.HIGH


def test_handoff_create_bad_input():
    with pytest.raises(ValidationError):
        HandoffCreateInput(
            reason=HandoffReason.DISPUTE_CLAIM,
            summary="help",
        )


def test_handoff_create_output():
    receipt = Receipt(
        action="handoff.create",
        target_masked="ticket-***-5678",
        state_before=ResourceState.NONE,
        state_after=ResourceState.QUEUED,
        verified_at=datetime.now(timezone.utc),
        audit_id="audit-uuid-12345678",
    )
    out = HandoffCreateOutput(
        handoff_id="handoff-ticket-12345678",
        status=HandoffStatus.QUEUED,
        department=Department.FRAUD_OPERATIONS,
        queue_position=2,
        created_at=datetime.now(timezone.utc),
        receipt=receipt,
    )
    assert out.status == HandoffStatus.QUEUED
    assert out.receipt.state_after == ResourceState.QUEUED


# 10. kb.search
def test_kb_search_good_input():
    inp = KbSearchInput(
        query="como bloquear mi tarjeta robada",
        locale="es",
        limit=5,
    )
    assert inp.query == "como bloquear mi tarjeta robada"


def test_kb_search_bad_input():
    with pytest.raises(ValidationError):
        KbSearchInput(query="a")


def test_kb_search_output():
    item = KbSearchResultItem(
        article_id="kb-card-block-01",
        title="Bloqueo preventivo de tarjetas",
        snippet="Pasos para bloquear inmediatamente tu tarjeta de débito o crédito...",
        category="security",
        score=0.94,
    )
    out = KbSearchOutput(results=[item])
    assert len(out.results) == 1
    assert out.results[0].score == 0.94
