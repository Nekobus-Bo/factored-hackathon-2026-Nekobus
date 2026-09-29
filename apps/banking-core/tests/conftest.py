"""Pytest fixtures for banking-core tests.

The DB-backed tests run against a dedicated, disposable database, never the dev
stack's: they delete the audit log and policy config and downgrade migrations.

* ``TEST_DATABASE_URL`` selects it. Default: database ``bank_test`` on the
  Postgres at 127.0.0.1:38432 (the port CI publishes). ``DATABASE_URL`` is
  deliberately ignored, so a dev or demo database cannot be picked up by accident.
* Its name must end in ``_test``; anything else aborts the whole run.
* It is created when missing and migrated to head once per session. The
  migrations need no extension (``vector`` is only created by ``infra/db/init.sql``
  for the compose database), so plain Postgres is enough.
* If nothing listens on the server's port, the DB-backed tests skip.
* The code under test reads ``DATABASE_URL``, so it points at the test database
  for the duration of the run.
"""

import os
import socket
from collections.abc import Generator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_TEST_DB_URL = (
    "postgresql+psycopg://app:dev-only-change-me@127.0.0.1:38432/bank_test"
)
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a network port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def _create_database_if_missing(url: URL) -> None:
    """Create the target database through the server's maintenance database."""
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if not exists:
                quoted = admin.dialect.identifier_preparer.quote(str(url.database))
                conn.execute(sa.text(f"CREATE DATABASE {quoted}"))
    finally:
        admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database_under_test() -> Generator[URL, None, None]:
    """Validate the test database and point the code under test at it."""
    url = make_url(os.getenv("TEST_DATABASE_URL") or DEFAULT_TEST_DB_URL)
    if not (url.database or "").endswith("_test"):
        pytest.exit(
            f"Refusing to run banking-core tests against database {url.database!r}: "
            "TEST_DATABASE_URL must name a database ending in '_test'. These tests "
            "delete audit and policy rows and downgrade migrations.",
            returncode=2,
        )
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        yield url


@pytest.fixture(scope="session")
def postgres_url(database_under_test: URL) -> str:
    """Create the test database if missing, migrate it to head, return its URL."""
    host = database_under_test.host or "localhost"
    port = database_under_test.port or 5432
    if not is_port_open(host, port):
        pytest.skip(
            f"Test Postgres is not accessible on {host}:{port} "
            "(set TEST_DATABASE_URL to point at one)"
        )
    _create_database_if_missing(database_under_test)
    # env.py resolves the URL from DATABASE_URL, set by `database_under_test`.
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    return database_under_test.render_as_string(hide_password=False)


@pytest.fixture
def db_engine(postgres_url: str) -> Generator[sa.Engine, None, None]:
    """Provide SQLAlchemy engine connected to test database."""
    engine = create_engine(postgres_url, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(postgres_url: str) -> Generator[Session, None, None]:
    """Provide a database session connected to Postgres, cleaning up after each test."""
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

        try:
            session.execute(sa.text("DELETE FROM config.tool_policy"))
            session.execute(sa.text("DELETE FROM config.policy_config"))
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
