"""Staging layer: typed Pydantic models and strict validation checks (docs/data.md §3).

Fails loudly naming the field on:
- Schema and types
- Keys and uniqueness
- Referential integrity
- Ranges and domains
- Completeness
"""

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError

from banking_core.models.enums import BlockReason, DocumentType

DataOrigin = Literal["synthetic", "dataset"]


class StagingValidationError(Exception):
    """Raised when data quality validation fails in the staging layer."""


class StagingCustomer(BaseModel):
    id: UUID
    document_type: DocumentType
    document_number: str
    full_name: str
    email: str
    phone: str
    birth_date: date
    preferred_locale: str
    registered_otp_channel: str
    created_at: datetime


class StagingAccount(BaseModel):
    id: UUID
    customer_id: UUID
    type: str
    currency: str
    available_balance_minor: int
    ledger_balance_minor: int
    status: str


class StagingCard(BaseModel):
    id: UUID
    account_id: UUID
    card_ref: str
    # Synthetic cards only. Dataset cards carry last4 and never the PAN.
    pan: str | None = None
    pan_last4: str
    brand: str
    status: str
    blocked_at: datetime | None = None
    blocked_reason: BlockReason | None = None
    # Dataset cards only.
    card_type: Literal["DEBIT", "CREDIT"] | None = None
    expiry_month: int | None = None
    expiry_year: int | None = None


class StagingTransaction(BaseModel):
    id: UUID
    account_id: UUID
    card_id: UUID | None = None
    amount_minor: int
    currency: str
    merchant: str
    mcc: str
    occurred_at: datetime
    status: str
    dispute_eligible: bool


class StagingDataset:
    """In-memory validated staging dataset."""

    def __init__(
        self,
        customers: list[StagingCustomer],
        accounts: list[StagingAccount],
        cards: list[StagingCard],
        transactions: list[StagingTransaction],
        origin: DataOrigin = "synthetic",
        source: str = "synthetic",
    ) -> None:
        self.customers = customers
        self.accounts = accounts
        self.cards = cards
        self.transactions = transactions
        self.origin: DataOrigin = origin
        self.source = source


def load_and_validate_staging(
    raw_dir: Path | str,
    origin: DataOrigin = "synthetic",
    source: str | None = None,
) -> StagingDataset:
    """Read raw JSONL files and run all 5 staging validation checks.

    ``origin`` selects the origin-specific rules: synthetic data must follow the
    demo locale→currency convention and carries a synthetic PAN; dataset data
    keeps its own currencies and must never carry a PAN (ADR-0011).

    Fails loudly naming the field on any check failure.
    """
    path = Path(raw_dir)
    cust_file = path / "customers.jsonl"
    acc_file = path / "accounts.jsonl"
    card_file = path / "cards.jsonl"
    tx_file = path / "transactions.jsonl"

    for required_file in [cust_file, acc_file, card_file, tx_file]:
        if not required_file.exists():
            raise StagingValidationError(
                f"Missing required staging file: {required_file.name}"
            )

    # 1. Schema & Types validation
    customers: list[StagingCustomer] = []
    accounts: list[StagingAccount] = []
    cards: list[StagingCard] = []
    transactions: list[StagingTransaction] = []

    # Read and parse customers
    with open(cust_file, encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            if not line.strip():
                continue
            raw_dict = json.loads(line)
            try:
                customers.append(StagingCustomer.model_validate(raw_dict))
            except ValidationError as e:
                first_err = e.errors()[0]
                field_name = ".".join(str(loc) for loc in first_err["loc"])
                raise StagingValidationError(
                    f"Schema error in customer.{field_name} (line {idx}): "
                    f"{first_err['msg']}"
                ) from e

    # Read and parse accounts
    with open(acc_file, encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            if not line.strip():
                continue
            raw_dict = json.loads(line)
            try:
                accounts.append(StagingAccount.model_validate(raw_dict))
            except ValidationError as e:
                first_err = e.errors()[0]
                field_name = ".".join(str(loc) for loc in first_err["loc"])
                raise StagingValidationError(
                    f"Schema error in account.{field_name} (line {idx}): "
                    f"{first_err['msg']}"
                ) from e

    # Read and parse cards
    with open(card_file, encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            if not line.strip():
                continue
            raw_dict = json.loads(line)
            try:
                cards.append(StagingCard.model_validate(raw_dict))
            except ValidationError as e:
                first_err = e.errors()[0]
                field_name = ".".join(str(loc) for loc in first_err["loc"])
                raise StagingValidationError(
                    f"Schema error in card.{field_name} (line {idx}): "
                    f"{first_err['msg']}"
                ) from e

    # Read and parse transactions
    with open(tx_file, encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            if not line.strip():
                continue
            raw_dict = json.loads(line)
            try:
                transactions.append(StagingTransaction.model_validate(raw_dict))
            except ValidationError as e:
                first_err = e.errors()[0]
                field_name = ".".join(str(loc) for loc in first_err["loc"])
                raise StagingValidationError(
                    f"Schema error in transaction.{field_name} (line {idx}): "
                    f"{first_err['msg']}"
                ) from e

    # 2. Keys and uniqueness checks
    seen_cust_ids: set[UUID] = set()
    seen_cust_docs: set[tuple[str, str]] = set()
    for c in customers:
        if c.id in seen_cust_ids:
            raise StagingValidationError(
                f"Uniqueness violation on customer.id: duplicate '{c.id}'"
            )
        seen_cust_ids.add(c.id)

        clean_doc = re.sub(r"[^A-Za-z0-9]", "", c.document_number).upper()
        doc_key = (c.document_type.value, clean_doc)
        if doc_key in seen_cust_docs:
            raise StagingValidationError(
                "Uniqueness violation on customer.document_number: "
                f"duplicate '{c.document_number}' for type '{c.document_type}'"
            )
        seen_cust_docs.add(doc_key)

    seen_acc_ids: set[UUID] = set()
    for a in accounts:
        if a.id in seen_acc_ids:
            raise StagingValidationError(
                f"Uniqueness violation on account.id: duplicate '{a.id}'"
            )
        seen_acc_ids.add(a.id)

    seen_card_ids: set[UUID] = set()
    seen_card_refs: set[str] = set()
    for cd in cards:
        if cd.id in seen_card_ids:
            raise StagingValidationError(
                f"Uniqueness violation on card.id: duplicate '{cd.id}'"
            )
        seen_card_ids.add(cd.id)

        if cd.card_ref in seen_card_refs:
            raise StagingValidationError(
                f"Uniqueness violation on card.card_ref: duplicate '{cd.card_ref}'"
            )
        seen_card_refs.add(cd.card_ref)

    seen_tx_ids: set[UUID] = set()
    for tx in transactions:
        if tx.id in seen_tx_ids:
            raise StagingValidationError(
                f"Uniqueness violation on transaction.id: duplicate '{tx.id}'"
            )
        seen_tx_ids.add(tx.id)

    # 3. Referential integrity checks
    customer_lookup = {c.id: c for c in customers}
    account_lookup = {a.id: a for a in accounts}
    card_lookup = {cd.id: cd for cd in cards}

    for a in accounts:
        if a.customer_id not in customer_lookup:
            raise StagingValidationError(
                "Referential integrity failure on account.customer_id: "
                f"customer '{a.customer_id}' does not exist"
            )

    for cd in cards:
        if cd.account_id not in account_lookup:
            raise StagingValidationError(
                "Referential integrity failure on card.account_id: "
                f"account '{cd.account_id}' does not exist"
            )

    for tx in transactions:
        if tx.account_id not in account_lookup:
            raise StagingValidationError(
                "Referential integrity failure on transaction.account_id: "
                f"account '{tx.account_id}' does not exist"
            )
        if tx.card_id is not None:
            if tx.card_id not in card_lookup:
                raise StagingValidationError(
                    "Referential integrity failure on transaction.card_id: "
                    f"card '{tx.card_id}' does not exist"
                )
            linked_card = card_lookup[tx.card_id]
            if linked_card.account_id != tx.account_id:
                raise StagingValidationError(
                    "Referential integrity failure on transaction.card_id: "
                    f"card '{tx.card_id}' belongs to account "
                    f"'{linked_card.account_id}' but transaction is on account "
                    f"'{tx.account_id}'"
                )

    # 4. Ranges and domains checks
    now = datetime.now(UTC)
    max_history_cutoff = now - timedelta(days=125)
    currency_regex = re.compile(r"^[A-Z]{3}$")

    for c in customers:
        if c.preferred_locale not in {"es", "pt", "en"}:
            raise StagingValidationError(
                "Range/domain violation on customer.preferred_locale: "
                f"invalid '{c.preferred_locale}'"
            )
        if not c.phone.startswith("+"):
            raise StagingValidationError(
                f"Range/domain violation on customer.phone: '{c.phone}' "
                "must start with '+' (E.164)"
            )
        if "@example." not in c.email.lower():
            raise StagingValidationError(
                f"Range/domain violation on customer.email: '{c.email}' "
                "must be an example.com domain (fake PII)"
            )
        if c.registered_otp_channel not in {"sms", "email", "NONE"}:
            raise StagingValidationError(
                "Range/domain violation on customer.registered_otp_channel: "
                f"invalid '{c.registered_otp_channel}'"
            )

    expected_currencies = {"es": "COP", "pt": "BRL", "en": "USD"}
    for a in accounts:
        if not currency_regex.match(a.currency):
            raise StagingValidationError(
                "Range/domain violation on account.currency: "
                f"'{a.currency}' is not 3 uppercase letters"
            )
        parent_cust = customer_lookup[a.customer_id]
        expected_curr = expected_currencies[parent_cust.preferred_locale]
        # The locale→currency convention belongs to the synthetic demo data only;
        # delivered datasets keep the currency of each product.
        if origin == "synthetic" and a.currency != expected_curr:
            raise StagingValidationError(
                "Range/domain violation on account.currency: account currency "
                f"'{a.currency}' does not match customer locale "
                f"'{parent_cust.preferred_locale}' (expected '{expected_curr}')"
            )
        if a.available_balance_minor < 0 or a.ledger_balance_minor < 0:
            raise StagingValidationError(
                "Range/domain violation on account.available_balance_minor: "
                "negative balance not allowed"
            )

    for cd in cards:
        if cd.status not in {"ACTIVE", "BLOCKED"}:
            raise StagingValidationError(
                f"Range/domain violation on card.status: invalid '{cd.status}'"
            )
        if cd.status == "BLOCKED":
            if cd.blocked_at is None:
                raise StagingValidationError(
                    "Range/domain violation on card.blocked_at: BLOCKED card "
                    f"'{cd.card_ref}' missing blocked_at"
                )
            if cd.blocked_reason is None:
                raise StagingValidationError(
                    "Range/domain violation on card.blocked_reason: BLOCKED "
                    f"card '{cd.card_ref}' missing blocked_reason"
                )
        else:
            if cd.blocked_at is not None or cd.blocked_reason is not None:
                raise StagingValidationError(
                    "Range/domain violation on card.blocked_at: ACTIVE card "
                    f"'{cd.card_ref}' must not have blocked_at or blocked_reason"
                )
        if len(cd.pan_last4) != 4 or not cd.pan_last4.isdigit():
            raise StagingValidationError(
                f"Range/domain violation on card.pan_last4: card '{cd.card_ref}' "
                "must have 4 digits"
            )
        if origin == "dataset":
            if cd.pan is not None:
                raise StagingValidationError(
                    f"Range/domain violation on card.pan: dataset card "
                    f"'{cd.card_ref}' must not carry a PAN"
                )
        else:
            if cd.pan is None or len(cd.pan) != 16 or not cd.pan.isdigit():
                raise StagingValidationError(
                    f"Range/domain violation on card.pan: card '{cd.card_ref}' "
                    "must have a 16-digit synthetic PAN"
                )
            if cd.pan_last4 != cd.pan[-4:]:
                raise StagingValidationError(
                    f"Range/domain violation on card.pan_last4: '{cd.pan_last4}' "
                    "does not match pan end"
                )
        if (cd.expiry_month is None) != (cd.expiry_year is None) or (
            cd.expiry_month is not None and not 1 <= cd.expiry_month <= 12
        ):
            raise StagingValidationError(
                f"Range/domain violation on card.expiry_month: card '{cd.card_ref}' "
                "needs both expiry fields with a month in 1..12"
            )

    for tx in transactions:
        if tx.amount_minor <= 0:
            raise StagingValidationError(
                "Range/domain violation on transaction.amount_minor: "
                f"non-positive amount '{tx.amount_minor}'"
            )
        parent_acc = account_lookup[tx.account_id]
        if tx.currency != parent_acc.currency:
            raise StagingValidationError(
                "Range/domain violation on transaction.currency: transaction "
                f"currency '{tx.currency}' does not match account currency "
                f"'{parent_acc.currency}'"
            )
        if tx.occurred_at < max_history_cutoff:
            raise StagingValidationError(
                "Range/domain violation on transaction.occurred_at: transaction "
                f"date '{tx.occurred_at}' older than 125 days"
            )
        if tx.occurred_at > now + timedelta(minutes=15):
            raise StagingValidationError(
                "Range/domain violation on transaction.occurred_at: transaction "
                f"date '{tx.occurred_at}' in the future"
            )

    # 5. Completeness checks (null check on non-nullable domain attributes)
    for c in customers:
        for field in [
            "id",
            "document_type",
            "document_number",
            "full_name",
            "email",
            "phone",
            "birth_date",
            "preferred_locale",
            "registered_otp_channel",
        ]:
            if getattr(c, field) is None:
                raise StagingValidationError(
                    f"Completeness violation on customer.{field}: "
                    "null value not allowed"
                )

    for a in accounts:
        for field in [
            "id",
            "customer_id",
            "type",
            "currency",
            "available_balance_minor",
            "ledger_balance_minor",
            "status",
        ]:
            if getattr(a, field) is None:
                raise StagingValidationError(
                    f"Completeness violation on account.{field}: null value not allowed"
                )

    for cd in cards:
        for field in [
            "id",
            "account_id",
            "card_ref",
            "pan_last4",
            "brand",
            "status",
        ]:
            if getattr(cd, field) is None:
                raise StagingValidationError(
                    f"Completeness violation on card.{field}: null value not allowed"
                )

    for tx in transactions:
        for field in [
            "id",
            "account_id",
            "amount_minor",
            "currency",
            "merchant",
            "mcc",
            "occurred_at",
            "status",
            "dispute_eligible",
        ]:
            if getattr(tx, field) is None:
                raise StagingValidationError(
                    f"Completeness violation on transaction.{field}: "
                    "null value not allowed"
                )

    return StagingDataset(
        customers=customers,
        accounts=accounts,
        cards=cards,
        transactions=transactions,
        origin=origin,
        source=source or origin,
    )
