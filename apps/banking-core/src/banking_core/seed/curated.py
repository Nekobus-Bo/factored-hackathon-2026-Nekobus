"""Curated layer: loads staging data into PostgreSQL with encryption."""

import os
from datetime import UTC, datetime

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


def load_curated_data(
    staging: StagingDataset,
    session: Session | None = None,
    master_key: str | bytes | None = None,
    blind_index_salt: str | bytes | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Idempotently load staging data into PostgreSQL core_bank tables.

    - Refuses to run when APP_ENV=production unless force=True
    - Truncates existing tables and loads all entities inside ONE atomic transaction
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

        # 2. Insert Customers with encrypted PII and blind indexes
        db_customers: list[Customer] = []
        for c in staging.customers:
            encryptor = RecordEncryptor(
                schema="core_bank",
                table="customer",
                record_id=c.id,
                master_key=resolved_master_key,
            )

            doc_enc = encryptor.encrypt("document_number_enc", c.document_number)
            name_enc = encryptor.encrypt("full_name_enc", c.full_name)
            email_enc = encryptor.encrypt("email_enc", c.email)
            phone_enc = encryptor.encrypt("phone_enc", c.phone)
            birth_enc = encryptor.encrypt("birth_date_enc", c.birth_date.isoformat())

            doc_bidx = compute_blind_index(
                value=c.document_number,
                field_name="document_number",
                salt=resolved_salt,
                document_type=c.document_type,
            )
            email_bidx = compute_blind_index(
                value=c.email,
                field_name="email",
                salt=resolved_salt,
            )
            phone_bidx = compute_blind_index(
                value=c.phone,
                field_name="phone",
                salt=resolved_salt,
            )

            db_customers.append(
                Customer(
                    id=c.id,
                    document_type=c.document_type,
                    document_number_enc=doc_enc,
                    document_number_bidx=doc_bidx,
                    full_name_enc=name_enc,
                    email_enc=email_enc,
                    email_bidx=email_bidx,
                    phone_enc=phone_enc,
                    phone_bidx=phone_bidx,
                    birth_date_enc=birth_enc,
                    preferred_locale=c.preferred_locale,
                    registered_otp_channel=c.registered_otp_channel,
                    data_origin="synthetic",
                    created_at=c.created_at,
                    source_ref="synthetic/customers.jsonl",
                    loaded_at=now,
                    code_version=CODE_VERSION,
                )
            )

        db_session.add_all(db_customers)

        # 3. Insert Accounts
        db_accounts: list[Account] = []
        for a in staging.accounts:
            db_accounts.append(
                Account(
                    id=a.id,
                    customer_id=a.customer_id,
                    type=a.type,
                    currency=a.currency,
                    available_balance_minor=a.available_balance_minor,
                    ledger_balance_minor=a.ledger_balance_minor,
                    status=a.status,
                    data_origin="synthetic",
                    source_ref="synthetic/accounts.jsonl",
                    loaded_at=now,
                    code_version=CODE_VERSION,
                )
            )

        db_session.add_all(db_accounts)

        # 4. Insert Cards with encrypted PAN
        db_cards: list[Card] = []
        for cd in staging.cards:
            card_encryptor = RecordEncryptor(
                schema="core_bank",
                table="card",
                record_id=cd.id,
                master_key=resolved_master_key,
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
                    data_origin="synthetic",
                    source_ref="synthetic/cards.jsonl",
                    loaded_at=now,
                    code_version=CODE_VERSION,
                )
            )

        db_session.add_all(db_cards)

        # 5. Insert Transactions in batches
        BATCH_SIZE = 1000
        for i in range(0, len(staging.transactions), BATCH_SIZE):
            chunk = staging.transactions[i : i + BATCH_SIZE]
            db_txs = [
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
                    data_origin="synthetic",
                    source_ref="synthetic/transactions.jsonl",
                    loaded_at=now,
                    code_version=CODE_VERSION,
                )
                for tx in chunk
            ]
            db_session.add_all(db_txs)

        # 6. Single atomic commit for truncate + all tables
        db_session.commit()

        # 7. Read actual counts from the database to return verified receipt
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
