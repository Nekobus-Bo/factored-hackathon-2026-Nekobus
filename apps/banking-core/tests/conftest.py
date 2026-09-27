"""Pytest fixtures for banking-core tests.

Supports testcontainers-free fixtures connected to the isolated compose Postgres
(using either DATABASE_URL or the compose proxy port 38432).
"""

import os
import socket
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_TEST_DB_URL = "postgresql+psycopg://app:dev-only-change-me@127.0.0.1:38432/bank"


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a network port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


@pytest.fixture(scope="session")
def postgres_url() -> str | None:
    """Resolve Postgres connection URL for compose DB testing."""
    resolved: str | None = None
    if url := os.getenv("DATABASE_URL"):
        resolved = url
    elif is_port_open("127.0.0.1", 38432):
        resolved = DEFAULT_TEST_DB_URL

    if resolved:
        os.environ["DATABASE_URL"] = resolved
    return resolved


@pytest.fixture
def db_engine(postgres_url: str | None) -> Generator[sa.Engine, None, None]:
    """Provide SQLAlchemy engine connected to test database."""
    if postgres_url is None:
        pytest.skip("Compose Postgres database is not accessible on 127.0.0.1:38432")

    engine = create_engine(postgres_url, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(postgres_url: str | None) -> Generator[Session, None, None]:
    """Provide a database session connected to Postgres, cleaning up after each test."""
    if postgres_url is None:
        pytest.skip("Compose Postgres database is not accessible on 127.0.0.1:38432")

    engine = create_engine(postgres_url, echo=False)
    SessionMaker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionMaker()

    def clean_tables() -> None:
        try:
            # Disable triggers to allow test cleanup
            session.execute(
                sa.text(
                    "ALTER TABLE ops.audit_log "
                    "DISABLE TRIGGER audit_log_prevent_modification"
                )
            )
            session.execute(
                sa.text(
                    "ALTER TABLE ops.audit_log "
                    "DISABLE TRIGGER audit_log_prevent_truncate"
                )
            )
            session.execute(sa.text("DELETE FROM ops.audit_log"))
            session.execute(
                sa.text(
                    "ALTER TABLE ops.audit_log "
                    "ENABLE TRIGGER audit_log_prevent_truncate"
                )
            )
            session.execute(
                sa.text(
                    "ALTER TABLE ops.audit_log "
                    "ENABLE TRIGGER audit_log_prevent_modification"
                )
            )
            session.execute(sa.text("DELETE FROM ops.idempotency_key"))
            session.commit()
        except Exception:
            session.rollback()

    clean_tables()
    try:
        yield session
    finally:
        clean_tables()
        session.close()
        engine.dispose()
