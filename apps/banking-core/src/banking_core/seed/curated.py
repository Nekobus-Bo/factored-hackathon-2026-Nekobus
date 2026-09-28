"""Curated layer: loads staging data into PostgreSQL with encryption."""

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from banking_core.crypto import (
    RecordEncryptor,
    compute_blind_index,
    get_master_key,
)
from banking_core.db import get_db
from banking_core.models.core_bank import Account, Card, Customer, Transaction
from banking_core.seed.staging import StagingDataset

CODE_VERSION = "v0.1.0"
TX_BATCH_SIZE = 1000


@dataclass
class CollisionCounts:
    """Dataset customers skipped because they collide with an earlier source."""

    customers: int = 0
    by_field: dict[str, int] = field(
        default_factory=lambda: {"document_number": 0, "email": 0, "phone": 0}
    )
    accounts: int = 0
    cards: int = 0
    transactions: int = 0


@dataclass
class _Indexes:
    """Blind indexes already loaded in this run, used for collision checks."""

    document: set[tuple[str, str]] = field(default_factory=set)
    email: set[str] = field(default_factory=set)
    phone: set[str] = field(default_factory=set)


def load_curated_data(
    staging: StagingDataset,
    session: Session | None = None,
    master_key: str | bytes | None = None,
    blind_index_salt: str | bytes | None = None,
    force: bool = False,
    dataset_sources: Sequence[StagingDataset] = (),
) -> dict[str, int]:
    """Idempotently load staging data into PostgreSQL core_bank tables.

    - Refuses to run when APP_ENV=production unless force=True
    - Truncates existing tables and loads all entities inside ONE atomic transaction
    - Loads ``staging`` (the synthetic demo data) first, then each dataset source
    - Skips any dataset customer whose document, email or phone blind index
      collides with one already loaded (demo identities win), together with
      their accounts, cards and transactions; the skips are counted
    - Encrypts PII per record using RecordEncryptor
    - Generates HMAC-SHA256 blind indexes for document, email, and phone
    - Populates lineage columns (data_origin, source_ref, loaded_at, code_version)
    """
    app_env = os.getenv("APP_ENV", "development").lower()
    if app_env == "production" and not force:
        raise RuntimeError(
            "Refusing to seed database in production (APP_ENV=production). "
            "Seeding truncates existing banking records. Pass --force to override."
        )

    resolved_master_key = get_master_key(master_key)
    resolved_salt = blind_index_salt or os.getenv("BLIND_INDEX_SALT")
    if not resolved_salt:
        raise ValueError("BLIND_INDEX_SALT is required for curated data loading")

    sess_generator = None
    if session is None:
        sess_generator = get_db()
        db_session = next(sess_generator)
    else:
        db_session = session

    try:
        now = datetime.now(UTC)

        # 1. Truncate core_bank tables for idempotency (inside transaction)
        db_session.execute(
            text(
                "TRUNCATE TABLE "
                "core_bank.transaction, "
                "core_bank.card, "
                "core_bank.account, "
                "core_bank.customer "
                "CASCADE;"
            )
        )

        indexes = _Indexes()
        _load_source(
            db_session,
            staging,
            origin="synthetic",
            source="synthetic",
            master_key=resolved_master_key,
            salt=resolved_salt,
            now=now,
            indexes=indexes,
            collisions=None,
        )
        collisions = CollisionCounts()
        for dataset in dataset_sources:
            _load_source(
                db_session,
                dataset,
                origin=dataset.origin,
                source=dataset.source,
                master_key=resolved_master_key,
                salt=resolved_salt,
                now=now,
                indexes=indexes,
                collisions=collisions,
            )

        # Single atomic commit for truncate + all tables
        db_session.commit()

        # Read actual counts from the database to return verified receipt
        counts = {
            "customer": db_session.scalar(
                select(text("COUNT(*) FROM core_bank.customer"))
            ),
            "account": db_session.scalar(
                select(text("COUNT(*) FROM core_bank.account"))
            ),
            "card": db_session.scalar(select(text("COUNT(*) FROM core_bank.card"))),
            "transaction": db_session.scalar(
                select(text("COUNT(*) FROM core_bank.transaction"))
            ),
        }
        if dataset_sources:
            counts["collision_customers_skipped"] = collisions.customers
            for field_name, n in collisions.by_field.items():
                counts[f"collision_{field_name}"] = n
            counts["collision_accounts_skipped"] = collisions.accounts
            counts["collision_cards_skipped"] = collisions.cards
            counts["collision_transactions_skipped"] = collisions.transactions
        return counts

    except Exception:
        db_session.rollback()
        raise

    finally:
        if sess_generator is not None:
            try:
                next(sess_generator)
            except StopIteration:
                pass


def _load_source(
    db_session: Session,
    staging: StagingDataset,
    *,
    origin: str,
    source: str,
    master_key: str | bytes,
    salt: str | bytes,
    now: datetime,
    indexes: _Indexes,
    collisions: CollisionCounts | None,
) -> None:
    """Add one staging source to the session.

    With ``collisions`` set, customers colliding with ``indexes`` are skipped
    (with everything that hangs from them) and counted; otherwise every
    customer is loaded. Either way the loaded customers extend ``indexes``.
    """
    # 1. Customers with encrypted PII and blind indexes
    db_customers: list[Customer] = []
    kept_customers: set[UUID] = set()
    for c in staging.customers:
        doc_bidx = compute_blind_index(
            value=c.document_number,
            field_name="document_number",
            salt=salt,
            document_type=c.document_type,
        )
        email_bidx = compute_blind_index(value=c.email, field_name="email", salt=salt)
        phone_bidx = compute_blind_index(value=c.phone, field_name="phone", salt=salt)
        doc_key = (str(c.document_type), doc_bidx)

        if collisions is not None:
            hits = [
                name
                for name, hit in (
                    ("document_number", doc_key in indexes.document),
                    ("email", email_bidx in indexes.email),
                    ("phone", phone_bidx in indexes.phone),
                )
                if hit
            ]
            if hits:
                collisions.customers += 1
                for name in hits:
                    collisions.by_field[name] += 1
                continue

        indexes.document.add(doc_key)
        indexes.email.add(email_bidx)
        indexes.phone.add(phone_bidx)
        kept_customers.add(c.id)

        encryptor = RecordEncryptor(
            schema="core_bank",
            table="customer",
            record_id=c.id,
            master_key=master_key,
        )
        db_customers.append(
            Customer(
                id=c.id,
                document_type=c.document_type,
                document_number_enc=encryptor.encrypt(
                    "document_number_enc", c.document_number
                ),
                document_number_bidx=doc_bidx,
                full_name_enc=encryptor.encrypt("full_name_enc", c.full_name),
                email_enc=encryptor.encrypt("email_enc", c.email),
                email_bidx=email_bidx,
                phone_enc=encryptor.encrypt("phone_enc", c.phone),
                phone_bidx=phone_bidx,
                birth_date_enc=encryptor.encrypt(
                    "birth_date_enc", c.birth_date.isoformat()
                ),
                preferred_locale=c.preferred_locale,
                registered_otp_channel=c.registered_otp_channel,
                data_origin=origin,
                created_at=c.created_at,
                source_ref=f"{source}/customers.jsonl",
                loaded_at=now,
                code_version=CODE_VERSION,
            )
        )
    db_session.add_all(db_customers)

    # 2. Accounts
    db_accounts: list[Account] = []
    kept_accounts: set[UUID] = set()
    for a in staging.accounts:
        if a.customer_id not in kept_customers:
            if collisions is not None:
                collisions.accounts += 1
            continue
        kept_accounts.add(a.id)
        db_accounts.append(
            Account(
                id=a.id,
                customer_id=a.customer_id,
                type=a.type,
                currency=a.currency,
                available_balance_minor=a.available_balance_minor,
                ledger_balance_minor=a.ledger_balance_minor,
                status=a.status,
                data_origin=origin,
                source_ref=f"{source}/accounts.jsonl",
                loaded_at=now,
                code_version=CODE_VERSION,
            )
        )
    db_session.add_all(db_accounts)

    # 3. Cards; only synthetic cards carry an (encrypted synthetic) PAN
    db_cards: list[Card] = []
    for cd in staging.cards:
        if cd.account_id not in kept_accounts:
            if collisions is not None:
                collisions.cards += 1
            continue
        pan_enc = None
        if cd.pan is not None:
            card_encryptor = RecordEncryptor(
                schema="core_bank",
                table="card",
                record_id=cd.id,
                master_key=master_key,
            )
            pan_enc = card_encryptor.encrypt("pan_enc", cd.pan)
        db_cards.append(
            Card(
                id=cd.id,
                account_id=cd.account_id,
                card_ref=cd.card_ref,
                pan_last4=cd.pan_last4,
                pan_enc=pan_enc,
                brand=cd.brand,
                status=cd.status,
                blocked_at=cd.blocked_at,
                blocked_reason=cd.blocked_reason,
                card_type=cd.card_type,
                expiry_month=cd.expiry_month,
                expiry_year=cd.expiry_year,
                data_origin=origin,
                source_ref=f"{source}/cards.jsonl",
                loaded_at=now,
                code_version=CODE_VERSION,
            )
        )
    db_session.add_all(db_cards)

    # 4. Transactions in batches
    kept_txs = []
    for tx in staging.transactions:
        if tx.account_id not in kept_accounts:
            if collisions is not None:
                collisions.transactions += 1
            continue
        kept_txs.append(tx)
    for i in range(0, len(kept_txs), TX_BATCH_SIZE):
        db_session.add_all(
            [
                Transaction(
                    id=tx.id,
                    account_id=tx.account_id,
                    card_id=tx.card_id,
                    amount_minor=tx.amount_minor,
                    currency=tx.currency,
                    merchant=tx.merchant,
                    mcc=tx.mcc,
                    occurred_at=tx.occurred_at,
                    status=tx.status,
                    dispute_eligible=tx.dispute_eligible,
                    data_origin=origin,
                    source_ref=f"{source}/transactions.jsonl",
                    loaded_at=now,
                    code_version=CODE_VERSION,
                )
                for tx in kept_txs[i : i + TX_BATCH_SIZE]
            ]
        )
