"""Scenario fixtures for demo walkthroughs and deterministic escalation test cases.

These fixtures provide predefined customers per language (es, pt, en) with known
credentials and states:
1. Demo Walkthrough: Known document number and a recent unrecognized charge. Its
   registered OTP channel is email (delivery is simulated in an in-app inbox).
2. Blocked Card: Customer with an already BLOCKED card (registered channel sms).
3. No OTP Channel: Customer with no registered OTP channel (must escalate to
   human backoffice).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import NAMESPACE_DNS, UUID, uuid5

from banking_core.models.enums import BlockReason, DocumentType

# Demo walkthrough documents per language matching .env.example
DEMO_CUSTOMER_DOCUMENT_ES = "1020304050"
DEMO_CUSTOMER_DOCUMENT_PT = "12345678900"
DEMO_CUSTOMER_DOCUMENT_EN = "P12345678"

# Blocked card fixture documents per language
BLOCKED_CARD_DOCUMENT_ES = "1020304051"
BLOCKED_CARD_DOCUMENT_PT = "12345678901"
BLOCKED_CARD_DOCUMENT_EN = "P12345679"

# No OTP channel fixture documents per language (must escalate)
NO_OTP_DOCUMENT_ES = "1020304052"
NO_OTP_DOCUMENT_PT = "98765432199"
NO_OTP_DOCUMENT_EN = "P12345670"


def fixture_uuid(name: str) -> UUID:
    """Generate a deterministic UUID from a fixture name."""
    return uuid5(NAMESPACE_DNS, f"pattern-blue.fixture.{name}")


@dataclass(frozen=True)
class FixtureBundle:
    """Bundle containing all entities associated with a scenario fixture."""

    customers: list[dict]
    accounts: list[dict]
    cards: list[dict]
    transactions: list[dict]


def create_scenario_fixtures(base_time: datetime | None = None) -> FixtureBundle:
    """Create all 9 scenario fixtures (3 per locale: es, pt, en)."""
    now = base_time or datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)

    customers: list[dict] = []
    accounts: list[dict] = []
    cards: list[dict] = []
    transactions: list[dict] = []

    configs = [
        (
            "es",
            "COP",
            "+57",
            (
                DEMO_CUSTOMER_DOCUMENT_ES,
                DocumentType.NATIONAL_ID.value,
                "Carlos Gomez",
            ),
            (
                BLOCKED_CARD_DOCUMENT_ES,
                DocumentType.NATIONAL_ID.value,
                "Elena Rodriguez",
            ),
            (
                NO_OTP_DOCUMENT_ES,
                DocumentType.NATIONAL_ID.value,
                "Mateo Morales",
            ),
        ),
        (
            "pt",
            "BRL",
            "+55",
            (
                DEMO_CUSTOMER_DOCUMENT_PT,
                DocumentType.NATIONAL_ID.value,
                "Mariana Silva",
            ),
            (
                BLOCKED_CARD_DOCUMENT_PT,
                DocumentType.NATIONAL_ID.value,
                "Lucas Santos",
            ),
            (
                NO_OTP_DOCUMENT_PT,
                DocumentType.NATIONAL_ID.value,
                "Lucas Oliveira",
            ),
        ),
        (
            "en",
            "USD",
            "+1",
            (
                DEMO_CUSTOMER_DOCUMENT_EN,
                DocumentType.PASSPORT.value,
                "Alice Johnson",
            ),
            (
                BLOCKED_CARD_DOCUMENT_EN,
                DocumentType.PASSPORT.value,
                "Bob Smith",
            ),
            (
                NO_OTP_DOCUMENT_EN,
                DocumentType.PASSPORT.value,
                "Carol White",
            ),
        ),
    ]

    for (
        locale,
        currency,
        phone_prefix,
        demo_spec,
        blocked_spec,
        no_otp_spec,
    ) in configs:
        demo_doc, demo_type, demo_name = demo_spec
        blocked_doc, blocked_type, blocked_name = blocked_spec
        no_otp_doc, no_otp_type, no_otp_name = no_otp_spec

        # ----------------------------------------------------------------------
        # 1. Demo Walkthrough Customer
        # ----------------------------------------------------------------------
        c_demo_id = fixture_uuid(f"{locale}-demo-customer")
        acc_demo_id = fixture_uuid(f"{locale}-demo-account")
        card_demo_id = fixture_uuid(f"{locale}-demo-card")
        unrec_tx_id = fixture_uuid(f"{locale}-demo-unrecognized-tx")

        if locale == "es":
            demo_phone = f"{phone_prefix}3001020304"
            demo_pan = "4532015099881050"
            demo_last4 = "1050"
            demo_brand = "VISA"
            demo_bal = 55000000
            unrec_amount = 35000000
            legit_amount = 2500000
        elif locale == "pt":
            demo_phone = f"{phone_prefix}11912345678"
            demo_pan = "5412755099881060"
            demo_last4 = "1060"
            demo_brand = "MASTERCARD"
            demo_bal = 180000
            unrec_amount = 48000
            legit_amount = 3500
        else:
            demo_phone = f"{phone_prefix}5559876543"
            demo_pan = "4111115099881070"
            demo_last4 = "1070"
            demo_brand = "VISA"
            demo_bal = 250000
            unrec_amount = 13999
            legit_amount = 1250

        customers.append(
            {
                "id": str(c_demo_id),
                "document_type": demo_type,
                "document_number": demo_doc,
                "full_name": demo_name,
                "email": f"demo.{locale}@example.com",
                "phone": demo_phone,
                "birth_date": date(1988, 5, 20).isoformat(),
                "preferred_locale": locale,
                # The demo simulates delivery as a "you got an email with the code"
                # notice in the web client (ADR-0007, amendment 2026-09-29).
                "registered_otp_channel": "email",
                "created_at": (now - timedelta(days=150)).isoformat(),
            }
        )

        accounts.append(
            {
                "id": str(acc_demo_id),
                "customer_id": str(c_demo_id),
                "type": "CHECKING",
                "currency": currency,
                "available_balance_minor": demo_bal,
                "ledger_balance_minor": demo_bal,
                "status": "ACTIVE",
            }
        )

        cards.append(
            {
                "id": str(card_demo_id),
                "account_id": str(acc_demo_id),
                "card_ref": f"card_demo_{locale}",
                "pan": demo_pan,
                "pan_last4": demo_last4,
                "brand": demo_brand,
                "status": "ACTIVE",
                "blocked_at": None,
                "blocked_reason": None,
            }
        )

        # Unrecognized charge (dispute walkthrough target)
        transactions.append(
            {
                "id": str(unrec_tx_id),
                "account_id": str(acc_demo_id),
                "card_id": str(card_demo_id),
                "amount_minor": unrec_amount,
                "currency": currency,
                "merchant": "Global Electronics Megastore",
                "mcc": "5732",
                "occurred_at": (now - timedelta(days=2, hours=3)).isoformat(),
                "status": "SETTLED",
                "dispute_eligible": True,
            }
        )

        # Legitimate recent transaction
        transactions.append(
            {
                "id": str(fixture_uuid(f"{locale}-demo-legit-tx")),
                "account_id": str(acc_demo_id),
                "card_id": str(card_demo_id),
                "amount_minor": legit_amount,
                "currency": currency,
                "merchant": "Local Artisan Bakery",
                "mcc": "5462",
                "occurred_at": (now - timedelta(days=1, hours=8)).isoformat(),
                "status": "SETTLED",
                "dispute_eligible": True,
            }
        )

        # ----------------------------------------------------------------------
        # 2. Already BLOCKED Card Customer
        # ----------------------------------------------------------------------
        c_blocked_id = fixture_uuid(f"{locale}-blocked-customer")
        acc_blocked_id = fixture_uuid(f"{locale}-blocked-account")
        card_blocked_id = fixture_uuid(f"{locale}-blocked-card")

        if locale == "es":
            blk_phone = f"{phone_prefix}3001020305"
            blk_pan = "4532015099882050"
            blk_last4 = "2050"
            blk_bal = 10000000
        elif locale == "pt":
            blk_phone = f"{phone_prefix}11912345679"
            blk_pan = "5412755099882060"
            blk_last4 = "2060"
            blk_bal = 50000
        else:
            blk_phone = f"{phone_prefix}5559876544"
            blk_pan = "4111115099882070"
            blk_last4 = "2070"
            blk_bal = 100000

        customers.append(
            {
                "id": str(c_blocked_id),
                "document_type": blocked_type,
                "document_number": blocked_doc,
                "full_name": blocked_name,
                "email": f"blocked.{locale}@example.com",
                "phone": blk_phone,
                "birth_date": date(1982, 9, 14).isoformat(),
                "preferred_locale": locale,
                "registered_otp_channel": "sms",
                "created_at": (now - timedelta(days=200)).isoformat(),
            }
        )

        accounts.append(
            {
                "id": str(acc_blocked_id),
                "customer_id": str(c_blocked_id),
                "type": "CHECKING",
                "currency": currency,
                "available_balance_minor": blk_bal,
                "ledger_balance_minor": blk_bal,
                "status": "ACTIVE",
            }
        )

        cards.append(
            {
                "id": str(card_blocked_id),
                "account_id": str(acc_blocked_id),
                "card_ref": f"card_blocked_{locale}",
                "pan": blk_pan,
                "pan_last4": blk_last4,
                "brand": "VISA",
                "status": "BLOCKED",
                "blocked_at": (now - timedelta(days=5)).isoformat(),
                "blocked_reason": BlockReason.SUSPICIOUS_ACTIVITY.value,
            }
        )

        # ----------------------------------------------------------------------
        # 3. No OTP Channel Customer (Must Escalate)
        # ----------------------------------------------------------------------
        c_no_otp_id = fixture_uuid(f"{locale}-no-otp-customer")
        acc_no_otp_id = fixture_uuid(f"{locale}-no-otp-account")
        card_no_otp_id = fixture_uuid(f"{locale}-no-otp-card")

        if locale == "es":
            no_otp_phone = f"{phone_prefix}3001020306"
            no_otp_pan = "4532015099883050"
            no_otp_last4 = "3050"
            no_otp_bal = 8000000
        elif locale == "pt":
            no_otp_phone = f"{phone_prefix}11912345680"
            no_otp_pan = "5412755099883060"
            no_otp_last4 = "3060"
            no_otp_bal = 40000
        else:
            no_otp_phone = f"{phone_prefix}5559876545"
            no_otp_pan = "4111115099883070"
            no_otp_last4 = "3070"
            no_otp_bal = 75000

        customers.append(
            {
                "id": str(c_no_otp_id),
                "document_type": no_otp_type,
                "document_number": no_otp_doc,
                "full_name": no_otp_name,
                "email": f"no.otp.{locale}@example.com",
                "phone": no_otp_phone,
                "birth_date": date(1991, 11, 28).isoformat(),
                "preferred_locale": locale,
                "registered_otp_channel": "NONE",
                "created_at": (now - timedelta(days=100)).isoformat(),
            }
        )

        accounts.append(
            {
                "id": str(acc_no_otp_id),
                "customer_id": str(c_no_otp_id),
                "type": "CHECKING",
                "currency": currency,
                "available_balance_minor": no_otp_bal,
                "ledger_balance_minor": no_otp_bal,
                "status": "ACTIVE",
            }
        )

        cards.append(
            {
                "id": str(card_no_otp_id),
                "account_id": str(acc_no_otp_id),
                "card_ref": f"card_no_otp_{locale}",
                "pan": no_otp_pan,
                "pan_last4": no_otp_last4,
                "brand": "VISA",
                "status": "ACTIVE",
                "blocked_at": None,
                "blocked_reason": None,
            }
        )

    return FixtureBundle(
        customers=customers,
        accounts=accounts,
        cards=cards,
        transactions=transactions,
    )
