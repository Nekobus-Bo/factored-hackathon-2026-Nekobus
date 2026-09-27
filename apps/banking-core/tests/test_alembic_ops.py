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


def test_alembic_0003_downgrade_to_0002_and_reupgrade(
    db_session: Session, postgres_url: str
) -> None:
    """Verify downgrade to 0002_ops_audit_idempotency drops config tables.

    Also verifies that re-upgrade to head restores them.
    """
    import os

    os.environ["DATABASE_URL"] = postgres_url
    os.environ.setdefault("POSTGRES_PASSWORD", "dev-only-change-me")
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)

    # 1. Downgrade to 0002_ops_audit_idempotency
    command.downgrade(alembic_cfg, "0002_ops_audit_idempotency")

    # Verify config schema and tables no longer exist
    res = db_session.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'config'"
        )
    ).fetchall()
    assert len(res) == 0

    # Verify ops tables still exist
    ops_res = db_session.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'ops'"
        )
    ).fetchall()
    ops_tables = {row[0] for row in ops_res}
    assert "audit_log" in ops_tables
    assert "idempotency_key" in ops_tables

    # 2. Re-upgrade to head (0003_config_policy)
    command.upgrade(alembic_cfg, "head")

    res_head = db_session.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'config'"
        )
    ).fetchall()
    config_tables = {row[0] for row in res_head}
    assert "policy_config" in config_tables
    assert "tool_policy" in config_tables


def test_alembic_0004_downgrade_drops_handoff_and_reupgrade(
    db_session: Session, postgres_url: str
) -> None:
    """Downgrade to 0003_config_policy drops ops.handoff; head restores it."""
    import os

    os.environ["DATABASE_URL"] = postgres_url
    os.environ.setdefault("POSTGRES_PASSWORD", "dev-only-change-me")
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)

    def ops_tables() -> set[str]:
        rows = db_session.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'ops'"
            )
        ).fetchall()
        return {row[0] for row in rows}

    command.downgrade(alembic_cfg, "0003_config_policy")
    assert "handoff" not in ops_tables()
    assert {"audit_log", "idempotency_key"} <= ops_tables()

    command.upgrade(alembic_cfg, "head")
    assert "handoff" in ops_tables()
