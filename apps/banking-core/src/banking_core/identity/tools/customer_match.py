"""Implementation of customer.match tool in banking-core.

Searches for matching customer records using HMAC-SHA256 blind index lookups
and document-type equivalence resolution (e.g. NATIONAL_ID == TAX_ID in pt market).
Responses are strictly indistinguishable for non-existent customers (ADR-0004).

execute_limited_customer_match adds the per-document limit across sessions
(control/attempt_limits.py): failed matches are counted per claimed document, by
its blind index, whether or not a customer with that document exists; past the
maximum the answer is matched=false without looking anything up.
"""

import hmac
import uuid
from functools import lru_cache
from typing import NamedTuple

import sqlalchemy as sa
from contracts.tools.customer_match import (
    CustomerMatchInput,
    CustomerMatchOutput,
)
from sqlalchemy.orm import Session

from banking_core.control.attempt_limits import AttemptLimits
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
from banking_core.models.enums import DocumentType

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


class CustomerMatchResult(NamedTuple):
    """Outcome of a limited customer.match."""

    output: CustomerMatchOutput
    customer_id: str | None
    # The per-document limit answered without looking anything up.
    limited: bool = False
    # Reference (blind-index prefix) of the document whose limit this very call
    # crossed: set on the first limited call of a window, for the audit event.
    limit_reached_ref: str | None = None


def _candidate_indexes(
    args: CustomerMatchInput,
    config: IdentityConfig,
    salt: str | bytes | None,
) -> list[tuple[DocumentType, str]]:
    """Blind index of the claimed number under each equivalent document type.

    A type under which the number is not valid is skipped: there is nothing to
    probe, and nothing to count.
    """
    candidates: list[tuple[DocumentType, str]] = []
    for doc_type in config.resolve_equivalent_document_types(args.document_type):
        try:
            bidx = compute_blind_index(
                value=args.document_number,
                field_name="document_number",
                salt=salt,
                document_type=doc_type,
            )
        except NormalizationError:
            continue
        candidates.append((doc_type, bidx))
    return candidates


def _find_customer(
    db_session: Session,
    args: CustomerMatchInput,
    candidates: list[tuple[DocumentType, str]],
    resolved_key: str | bytes,
) -> str | None:
    """Look the claim up; the id of the matching customer, or None."""
    expected_birth_date = (
        args.birth_date.isoformat() if args.birth_date is not None else None
    )
    matched_customer: Customer | None = None
    decrypted = False

    # Probe the blind index of each candidate document type
    for doc_type, bidx in candidates:
        stmt = sa.select(Customer).where(
            Customer.document_type == doc_type,
            Customer.document_number_bidx == bidx,
        )
        found = db_session.scalars(stmt).all()

        for c in found:
            # If birth_date was provided, verify with decrypted birth_date_enc
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

    return str(matched_customer.id) if matched_customer is not None else None


def execute_customer_match(
    db_session: Session,
    args: CustomerMatchInput,
    identity_config: IdentityConfig | None = None,
    master_key: str | bytes | None = None,
    salt: str | bytes | None = None,
) -> tuple[CustomerMatchOutput, str | None]:
    """Execute customer match against core_bank.customer records.

    salt=None loads BLIND_INDEX_SALT inside compute_blind_index, which fails
    closed if it is missing. This is the bare lookup: the per-document limit is
    applied by execute_limited_customer_match.

    Returns:
        tuple[CustomerMatchOutput, str | None]: (output, matched_customer_id)
    """
    config = identity_config or IdentityConfig.from_env()
    resolved_key = get_master_key(master_key)
    candidates = _candidate_indexes(args, config, salt)
    customer_id = _find_customer(db_session, args, candidates, resolved_key)
    if customer_id is not None:
        return CustomerMatchOutput(matched=True), customer_id

    # Indistinguishable output for non-existent or mismatched customer
    return CustomerMatchOutput(matched=False), None


def execute_limited_customer_match(
    db_session: Session,
    args: CustomerMatchInput,
    limits: AttemptLimits,
    identity_config: IdentityConfig | None = None,
    master_key: str | bytes | None = None,
    salt: str | bytes | None = None,
) -> CustomerMatchResult:
    """customer.match under the per-document failure limit, across sessions.

    The attempt is counted on the claimed document's blind index BEFORE anything
    is looked up (atomic, so parallel sessions cannot all pass a check), whether
    or not a customer with that document exists: the counter, the response and
    the work done are the same for both. A match gives its count back, so only
    failures stay counted. Past the maximum the answer is matched=false with no
    lookup at all.
    """
    config = identity_config or IdentityConfig.from_env()
    resolved_key = get_master_key(master_key)
    candidates = _candidate_indexes(args, config, salt)

    attempt = limits.reserve_document_attempt([bidx for _, bidx in candidates])
    if attempt.blocked:
        return CustomerMatchResult(
            CustomerMatchOutput(matched=False),
            None,
            limited=True,
            limit_reached_ref=attempt.limit_reached_ref,
        )

    customer_id = _find_customer(db_session, args, candidates, resolved_key)
    if customer_id is None:
        return CustomerMatchResult(CustomerMatchOutput(matched=False), None)
    limits.release_document_attempt(attempt)
    return CustomerMatchResult(CustomerMatchOutput(matched=True), customer_id)
