"""Implementation of customer.match tool in banking-core.

Searches for matching customer records using HMAC-SHA256 blind index lookups
and document-type equivalence resolution (e.g. NATIONAL_ID == TAX_ID in pt market).
Responses are strictly indistinguishable for non-existent customers (ADR-0004).
"""

import hmac
import uuid
from functools import lru_cache

import sqlalchemy as sa
from contracts.tools.customer_match import (
    CustomerMatchInput,
    CustomerMatchOutput,
)
from sqlalchemy.orm import Session

from banking_core.crypto import (
    DecryptionError,
    InvalidKeyError,
    NormalizationError,
    RecordEncryptor,
    compute_blind_index,
    get_master_key,
)
from banking_core.identity.config import IdentityConfig
from banking_core.models.core_bank import Customer

# Fixed record used only to spend a real decrypt when no candidate exists, so a
# miss costs about the same as a birth-date check on an existing customer.
_DUMMY_RECORD_ID = uuid.UUID(int=0)
_DUMMY_BIRTH_DATE = "1900-01-01"


@lru_cache(maxsize=4)
def _dummy_birth_date_token(master_key: str | bytes) -> str:
    encryptor = RecordEncryptor("core_bank", "customer", _DUMMY_RECORD_ID, master_key)
    return encryptor.encrypt("birth_date_enc", _DUMMY_BIRTH_DATE)


def _birth_date_matches(encryptor: RecordEncryptor, token: str, expected: str) -> bool:
    stored = encryptor.decrypt("birth_date_enc", token)
    return hmac.compare_digest(stored.encode(), expected.encode())


def execute_customer_match(
    db_session: Session,
    args: CustomerMatchInput,
    identity_config: IdentityConfig | None = None,
    master_key: str | bytes | None = None,
    salt: str | bytes | None = None,
) -> tuple[CustomerMatchOutput, str | None]:
    """Execute customer match against core_bank.customer records.

    salt=None loads BLIND_INDEX_SALT inside compute_blind_index, which fails
    closed if it is missing.

    Returns:
        tuple[CustomerMatchOutput, str | None]: (output, matched_customer_id)
    """
    config = identity_config or IdentityConfig.from_env()
    resolved_key = get_master_key(master_key)
    expected_birth_date = (
        args.birth_date.isoformat() if args.birth_date is not None else None
    )

    # 1. Resolve candidate equivalent document types from config
    candidate_types = config.resolve_equivalent_document_types(args.document_type)

    matched_customer: Customer | None = None
    decrypted = False

    # 2. Probe blind index for each candidate document type
    for doc_type in candidate_types:
        try:
            bidx = compute_blind_index(
                value=args.document_number,
                field_name="document_number",
                salt=salt,
                document_type=doc_type,
            )
        except NormalizationError:
            # Not a valid number for this document type: nothing to probe.
            continue

        stmt = sa.select(Customer).where(
            Customer.document_type == doc_type,
            Customer.document_number_bidx == bidx,
        )
        candidates = db_session.scalars(stmt).all()

        for c in candidates:
            # 3. If birth_date was provided, verify with decrypted birth_date_enc
            if expected_birth_date is not None:
                encryptor = RecordEncryptor(
                    schema="core_bank",
                    table="customer",
                    record_id=c.id,
                    master_key=resolved_key,
                )
                decrypted = True
                try:
                    if not _birth_date_matches(
                        encryptor, c.birth_date_enc, expected_birth_date
                    ):
                        continue
                except InvalidKeyError:
                    raise
                except DecryptionError:
                    continue

            # Verified customer match
            matched_customer = c
            break

        if matched_customer is not None:
            break

    if expected_birth_date is not None and not decrypted:
        dummy = RecordEncryptor("core_bank", "customer", _DUMMY_RECORD_ID, resolved_key)
        _birth_date_matches(
            dummy, _dummy_birth_date_token(resolved_key), expected_birth_date
        )

    if matched_customer is not None:
        return CustomerMatchOutput(matched=True), str(matched_customer.id)

    # Indistinguishable output for non-existent or mismatched customer
    return CustomerMatchOutput(matched=False), None
