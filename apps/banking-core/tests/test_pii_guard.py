"""Unit tests for audit log payload PII guard."""

import pytest
from banking_core.audit.pii_guard import PiiLeakError, check_payload


def test_pii_guard_rejects_unmasked_email() -> None:
    """Verify unmasked email in payload raises PiiLeakError."""
    payload = {
        "user": "juan",
        "contact": "juan.perez@bank.com",
    }
    with pytest.raises(PiiLeakError, match="Unmasked email detected"):
        check_payload(payload)


def test_pii_guard_accepts_masked_email() -> None:
    """Verify masked email in payload is accepted."""
    payload = {
        "contact_masked": "j***@bank.com",
        "alt_contact": "m*@domain.co",
    }
    check_payload(payload)


def test_pii_guard_rejects_unmasked_phone() -> None:
    """Verify unmasked phone number in payload raises PiiLeakError."""
    payloads = [
        {"phone": "+57 300 123 4567"},
        {"phone": "300-123-4567"},
        {"phone": "+1 800 555 0199"},
    ]
    for p in payloads:
        with pytest.raises(PiiLeakError, match="Unmasked phone number detected"):
            check_payload(p)


def test_pii_guard_accepts_masked_phone() -> None:
    """Verify masked phone number in payload is accepted."""
    payload = {
        "phone_masked": "+57 300 *** 4567",
        "short_masked": "*** 1234",
    }
    check_payload(payload)


def test_pii_guard_rejects_full_pan() -> None:
    """Verify 16-digit card numbers (raw or separated) raise PiiLeakError."""
    payloads = [
        {"card": "4111111111111111"},
        {"card": "4111-1111-1111-1111"},
        {"card": "4111 1111 1111 1111"},
        {"info": "Customer used card 4111111111111111 for transaction"},
    ]
    for p in payloads:
        with pytest.raises(PiiLeakError, match="Unmasked payment card PAN detected"):
            check_payload(p)


def test_pii_guard_accepts_masked_pan() -> None:
    """Verify masked PAN is accepted."""
    payload = {
        "target_masked": "**** **** **** 1234",
        "pan_masked": "************1234",
    }
    check_payload(payload)


def test_pii_guard_opaque_reference_pan_guard() -> None:
    """Verify opaque references with >= 12 digits are rejected."""
    good_payload = {"card_ref": "card_a1b2c3d4e5"}
    check_payload(good_payload)

    bad_payload = {"card_ref": "card_4111111111111111"}
    with pytest.raises(PiiLeakError, match="PAN guard"):
        check_payload(bad_payload)

    bad_separated = {"card_ref": "card_4111-1111-1111-1111"}
    with pytest.raises(PiiLeakError, match="PAN guard"):
        check_payload(bad_separated)


def test_pii_guard_rejects_unmasked_document_number() -> None:
    """Verify unmasked document numbers under doc keys raise PiiLeakError."""
    bad_payload = {"document_number": "1020304050"}
    with pytest.raises(PiiLeakError, match="Unmasked document number detected"):
        check_payload(bad_payload)

    good_payload = {"document_number": "****4050"}
    check_payload(good_payload)


def test_pii_guard_accepts_clean_business_payload() -> None:
    """Verify normal business metrics, timestamps, and enums are accepted."""
    payload = {
        "account_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "amount_minor": 150000,
        "currency": "COP",
        "occurred_at": "2026-09-26T22:00:00Z",
        "status": "SETTLED",
        "dispute_eligible": True,
        "tags": ["retail", "pos"],
    }
    check_payload(payload)


def test_pii_guard_rejects_reviewer_probes_numbers_and_keys() -> None:
    """Verify reviewer probes (int PAN, phone, doc, and email as key) are rejected."""
    # Probe 1: int PAN
    with pytest.raises(PiiLeakError, match="Unmasked payment card PAN"):
        check_payload({"card": 4111111111111111})

    # Probe 2: int phone
    with pytest.raises(PiiLeakError, match="Unmasked phone number"):
        check_payload({"phone": 573001234567})

    # Probe 3: int document number
    with pytest.raises(PiiLeakError, match="Unmasked document number"):
        check_payload({"document_number": 1020304050})

    # Probe 4: email in dictionary key
    with pytest.raises(PiiLeakError, match="Unmasked email detected"):
        check_payload({"alice@example.com": True})
