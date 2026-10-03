"""Policy configuration loader for banking-core.

Loads active policy configuration from the database (ADR-0002).
If no configuration is found in the database, seeds it from environment
variables on the first run.
"""

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from banking_core.control.policy import PolicyConfig
from banking_core.models.config import PolicyConfigRecord

logger = logging.getLogger(__name__)


def record_to_policy_config(record: PolicyConfigRecord) -> PolicyConfig:
    """Convert a database PolicyConfigRecord to a domain PolicyConfig."""
    raw_thresholds: dict[str, Any] = record.thresholds_minor or {}
    thresholds = {str(k).upper(): int(v) for k, v in raw_thresholds.items()}
    return PolicyConfig(
        thresholds_minor=thresholds,
        currency=record.currency,
        amount_mode=record.amount_mode,  # type: ignore[arg-type]
        rate_limit_attempts_per_session=record.rate_limit_attempts_per_session,
        otp_max_attempts=record.otp_max_attempts,
        otp_max_resends=record.otp_max_resends,
        otp_ttl_seconds=record.otp_ttl_seconds,
        session_ttl_seconds=record.session_ttl_seconds,
        customer_otp_max_failures=record.customer_otp_max_failures,
        customer_otp_window_seconds=record.customer_otp_window_seconds,
        customer_otp_lock_seconds=record.customer_otp_lock_seconds,
        document_match_max_failures=record.document_match_max_failures,
        document_match_window_seconds=record.document_match_window_seconds,
        handoff_reasons_requiring_identity_attempt=list(
            record.handoff_reasons_requiring_identity_attempt or []
        ),
    )


def load_policy_config(session: Session | None = None) -> PolicyConfig:
    """Load active policy configuration from database, seeding from env if empty.

    Fails loudly if the database is unreachable or configuration cannot be loaded.
    Never silently falls back to environment configuration.

    Args:
        session: Optional SQLAlchemy session. If None, acquires a session from
            banking_core.db.session.

    Returns:
        The active PolicyConfig loaded from the database.
    """
    if session is not None:
        return _load_or_seed(session)

    from banking_core.db.session import get_session_maker

    session_maker = get_session_maker()
    with session_maker() as sess:
        return _load_or_seed(sess)


def _load_or_seed(session: Session) -> PolicyConfig:
    """Internal helper to load active record or seed from env."""
    stmt = (
        sa.select(PolicyConfigRecord)
        .where(PolicyConfigRecord.is_active.is_(True))
        .order_by(PolicyConfigRecord.version.desc())
        .limit(1)
    )
    record = session.execute(stmt).scalar_one_or_none()
    if record is not None:
        return record_to_policy_config(record)

    # Empty table: seed from environment on first run. Concurrent first seeds
    # race on the unique version; the loser inserts nothing and re-reads.
    seed_config = PolicyConfig.from_env()
    insert_stmt = (
        pg_insert(PolicyConfigRecord)
        .values(
            version=1,
            is_active=True,
            currency=seed_config.currency,
            amount_mode=seed_config.amount_mode,
            thresholds_minor=seed_config.thresholds_minor,
            rate_limit_attempts_per_session=seed_config.rate_limit_attempts_per_session,
            otp_max_attempts=seed_config.otp_max_attempts,
            otp_max_resends=seed_config.otp_max_resends,
            otp_ttl_seconds=seed_config.otp_ttl_seconds,
            session_ttl_seconds=seed_config.session_ttl_seconds,
            customer_otp_max_failures=seed_config.customer_otp_max_failures,
            customer_otp_window_seconds=seed_config.customer_otp_window_seconds,
            customer_otp_lock_seconds=seed_config.customer_otp_lock_seconds,
            document_match_max_failures=seed_config.document_match_max_failures,
            document_match_window_seconds=seed_config.document_match_window_seconds,
            handoff_reasons_requiring_identity_attempt=[
                r.value for r in seed_config.handoff_reasons_requiring_identity_attempt
            ],
        )
        .on_conflict_do_nothing(index_elements=["version"])
    )
    session.execute(insert_stmt)
    session.commit()

    # Re-read active record
    record = session.execute(stmt).scalar_one_or_none()
    if record is not None:
        logger.info("Seeded initial policy config (v1) in database from environment")
        return record_to_policy_config(record)

    raise RuntimeError("Failed to load or seed policy config from database")


def save_policy_config(config: PolicyConfig, session: Session) -> PolicyConfigRecord:
    """Save an updated policy configuration as a new active version in the database.

    Deactivates existing active records and increments version number.
    """
    session.execute(
        sa.update(PolicyConfigRecord)
        .where(PolicyConfigRecord.is_active.is_(True))
        .values(is_active=False)
    )

    max_ver_stmt = sa.select(
        sa.func.coalesce(sa.func.max(PolicyConfigRecord.version), 0)
    )
    current_max = session.execute(max_ver_stmt).scalar_one()

    new_record = PolicyConfigRecord(
        version=current_max + 1,
        is_active=True,
        currency=config.currency,
        amount_mode=config.amount_mode,
        thresholds_minor=config.thresholds_minor,
        rate_limit_attempts_per_session=config.rate_limit_attempts_per_session,
        otp_max_attempts=config.otp_max_attempts,
        otp_max_resends=config.otp_max_resends,
        otp_ttl_seconds=config.otp_ttl_seconds,
        session_ttl_seconds=config.session_ttl_seconds,
        customer_otp_max_failures=config.customer_otp_max_failures,
        customer_otp_window_seconds=config.customer_otp_window_seconds,
        customer_otp_lock_seconds=config.customer_otp_lock_seconds,
        document_match_max_failures=config.document_match_max_failures,
        document_match_window_seconds=config.document_match_window_seconds,
        handoff_reasons_requiring_identity_attempt=[
            r.value for r in config.handoff_reasons_requiring_identity_attempt
        ],
    )
    session.add(new_record)
    session.commit()
    session.refresh(new_record)
    return new_record
