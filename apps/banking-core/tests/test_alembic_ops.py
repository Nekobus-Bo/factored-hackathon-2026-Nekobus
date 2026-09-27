"""Tests for Alembic migrations downgrade and upgrade repeatability."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session


def test_alembic_downgrade_and_upgrade(db_session: Session, postgres_url: str) -> None:
    """Verify clean downgrade to 0001_initial_schema and re-upgrade to head."""
    import os

    os.environ["DATABASE_URL"] = postgres_url
    os.environ.setdefault("POSTGRES_PASSWORD", "dev-only-change-me")
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)

    # 1. Downgrade to 0001_initial_schema
    command.downgrade(alembic_cfg, "0001_initial_schema")

    # Verify tables no longer exist in ops
    res = db_session.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'ops'"
        )
    ).fetchall()
    table_names = {row[0] for row in res}
    assert "audit_log" not in table_names
    assert "idempotency_key" not in table_names

    # 2. Re-upgrade to head
    command.upgrade(alembic_cfg, "head")

    # Verify tables exist again in ops
    res_after = db_session.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'ops'"
        )
    ).fetchall()
    table_names_after = {row[0] for row in res_after}
    assert "audit_log" in table_names_after
    assert "idempotency_key" in table_names_after
