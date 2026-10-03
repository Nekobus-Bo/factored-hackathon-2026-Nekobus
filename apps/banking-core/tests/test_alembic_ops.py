"""Tests for Alembic migrations downgrade and upgrade repeatability."""

from collections.abc import Generator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session


@pytest.fixture
def alembic_cfg(postgres_url: str) -> Generator[Config, None, None]:
    """Alembic config for the test database; always leaves it at head.

    The tests below downgrade on purpose. Restoring head on teardown, even when an
    assertion fails half way, keeps the rest of the suite independent of test order.
    """
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", postgres_url)
    try:
        yield cfg
    finally:
        command.upgrade(cfg, "head")


def test_alembic_downgrade_and_upgrade(
    db_session: Session, alembic_cfg: Config
) -> None:
    """Verify clean downgrade to 0001_initial_schema and re-upgrade to head."""
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
    db_session: Session, alembic_cfg: Config
) -> None:
    """Verify downgrade to 0002_ops_audit_idempotency drops config tables.

    Also verifies that re-upgrade to head restores them.
    """
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
    db_session: Session, alembic_cfg: Config
) -> None:
    """Downgrade to 0003_config_policy drops ops.handoff; head restores it."""

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


def _card_columns(db_session: Session) -> dict[str, str]:
    rows = db_session.execute(
        sa.text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'core_bank' AND table_name = 'card'"
        )
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def test_alembic_0005_dataset_cards_down_and_up(
    db_session: Session, alembic_cfg: Config
) -> None:
    """0005 makes pan_enc nullable and adds card_type/expiry; downgrade reverts."""
    command.downgrade(alembic_cfg, "0004_ops_handoff")
    columns = _card_columns(db_session)
    assert columns["pan_enc"] == "NO"
    assert "card_type" not in columns and "expiry_year" not in columns

    command.upgrade(alembic_cfg, "head")
    columns = _card_columns(db_session)
    assert columns["pan_enc"] == "YES"
    assert columns["card_type"] == "YES"
    assert columns["expiry_month"] == "YES" and columns["expiry_year"] == "YES"
    constraints = {
        row[0]
        for row in db_session.execute(
            sa.text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'core_bank.card'::regclass"
            )
        ).fetchall()
    }
    assert {
        "ck_card_pan_only_synthetic",
        "ck_card_card_type",
        "ck_card_expiry",
    } <= constraints


ATTEMPT_LIMIT_COLUMNS = {
    "customer_otp_max_failures": "5",
    "customer_otp_window_seconds": "3600",
    "customer_otp_lock_seconds": "1800",
    "document_match_max_failures": "10",
    "document_match_window_seconds": "3600",
}


def _policy_columns(db_session: Session) -> set[str]:
    rows = db_session.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'config' AND table_name = 'policy_config'"
        )
    ).fetchall()
    return {row[0] for row in rows}


def test_alembic_0006_attempt_limits_down_and_up(
    db_session: Session, alembic_cfg: Config
) -> None:
    """0006 adds the limit columns; rows saved before it take the seed defaults."""
    command.downgrade(alembic_cfg, "0005_dataset_cards")
    assert not set(ATTEMPT_LIMIT_COLUMNS) & _policy_columns(db_session)
    db_session.execute(
        sa.text(
            "INSERT INTO config.policy_config (version, is_active) VALUES (1, true)"
        )
    )
    db_session.commit()

    command.upgrade(alembic_cfg, "head")
    assert set(ATTEMPT_LIMIT_COLUMNS) <= _policy_columns(db_session)
    row = db_session.execute(
        sa.text(
            "SELECT "
            + ", ".join(ATTEMPT_LIMIT_COLUMNS)
            + " FROM config.policy_config WHERE version = 1"
        )
    ).one()
    assert [str(value) for value in row] == list(ATTEMPT_LIMIT_COLUMNS.values())


def _tool_policy_columns(db_session: Session) -> set[str]:
    rows = db_session.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'config' AND table_name = 'tool_policy'"
        )
    ).fetchall()
    db_session.commit()  # no lock held while alembic changes the table
    return {row[0] for row in rows}


def test_alembic_0007_tool_policy_versions_keep_saved_rows(
    db_session: Session, alembic_cfg: Config
) -> None:
    """0007 turns the per-tool rows into version 1; downgrading keeps the active one."""
    command.downgrade(alembic_cfg, "0006_attempt_limits")
    assert _tool_policy_columns(db_session) == {
        "tool_name",
        "permitted_states",
        "updated_at",
    }
    db_session.execute(
        sa.text(
            "INSERT INTO config.tool_policy (tool_name, permitted_states) VALUES "
            "('card.list', '[\"VERIFIED\"]'), ('account.get_summary', '[]')"
        )
    )
    db_session.commit()

    command.upgrade(alembic_cfg, "head")
    assert _tool_policy_columns(db_session) == {
        "id",
        "version",
        "is_active",
        "matrix",
        "created_at",
    }
    rows = db_session.execute(
        sa.text("SELECT version, is_active, matrix FROM config.tool_policy")
    ).all()
    db_session.commit()
    assert [(r.version, r.is_active, r.matrix) for r in rows] == [
        (1, True, {"card.list": ["VERIFIED"], "account.get_summary": []})
    ]

    # Only one version can be active; older versions are history.
    db_session.execute(sa.text("UPDATE config.tool_policy SET is_active = false"))
    db_session.execute(
        sa.text(
            "INSERT INTO config.tool_policy (version, is_active, matrix) "
            "VALUES (2, true, '{\"card.block\": []}')"
        )
    )
    db_session.commit()
    command.downgrade(alembic_cfg, "0006_attempt_limits")
    legacy = db_session.execute(
        sa.text("SELECT tool_name, permitted_states FROM config.tool_policy")
    ).all()
    db_session.commit()
    assert [(r.tool_name, r.permitted_states) for r in legacy] == [("card.block", [])]


def test_alembic_0007_leaves_an_empty_tool_policy_to_the_seed(
    db_session: Session, alembic_cfg: Config
) -> None:
    command.downgrade(alembic_cfg, "0006_attempt_limits")
    command.upgrade(alembic_cfg, "head")

    count = db_session.execute(sa.text("SELECT count(*) FROM config.tool_policy"))
    assert count.scalar_one() == 0
    db_session.commit()


def _handoff_columns(db_session: Session) -> dict[str, tuple[str, int | None]]:
    rows = db_session.execute(
        sa.text(
            "SELECT column_name, is_nullable, character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_schema = 'ops' AND table_name = 'handoff'"
        )
    ).all()
    db_session.commit()  # no lock held while alembic changes the table
    return {row[0]: (row[1], row[2]) for row in rows}


def test_alembic_0008_handoff_assignment_down_and_up(
    db_session: Session, alembic_cfg: Config
) -> None:
    """0008 adds the nullable assignment columns; rows saved before it keep working."""
    command.downgrade(alembic_cfg, "0007_tool_policy_versions")
    columns = _handoff_columns(db_session)
    assert "assigned_agent" not in columns and "assigned_at" not in columns
    db_session.execute(
        sa.text(
            "INSERT INTO ops.handoff (id, handoff_ref, session_ref, reason, priority, "
            "department, summary, idempotency_scope) VALUES (gen_random_uuid(), "
            "'hnd_migrationcheck', 'session-x', 'FRAUD', 'HIGH', 'FRAUD_OPERATIONS', "
            "'{}', 'scope')"
        )
    )
    db_session.commit()

    command.upgrade(alembic_cfg, "head")
    columns = _handoff_columns(db_session)
    assert columns["assigned_agent"] == ("YES", 254)
    assert columns["assigned_at"][0] == "YES"
    row = db_session.execute(
        sa.text(
            "SELECT status, assigned_agent, assigned_at FROM ops.handoff "
            "WHERE handoff_ref = 'hnd_migrationcheck'"
        )
    ).one()
    db_session.commit()
    assert (row.status, row.assigned_agent, row.assigned_at) == ("QUEUED", None, None)

    db_session.execute(
        sa.text(
            "UPDATE ops.handoff SET status = 'ASSIGNED', "
            "assigned_agent = 'ana@bank.example', assigned_at = now() "
            "WHERE handoff_ref = 'hnd_migrationcheck'"
        )
    )
    db_session.commit()
    command.downgrade(alembic_cfg, "0007_tool_policy_versions")
    columns = _handoff_columns(db_session)
    assert "assigned_agent" not in columns and "assigned_at" not in columns
    kept = db_session.execute(
        sa.text(
            "SELECT status FROM ops.handoff WHERE handoff_ref = 'hnd_migrationcheck'"
        )
    ).scalar_one()
    db_session.commit()
    assert kept == "ASSIGNED"

    db_session.execute(
        sa.text("DELETE FROM ops.handoff WHERE handoff_ref = 'hnd_migrationcheck'")
    )
    db_session.commit()


def test_alembic_0009_assistant_feedback_down_and_up(
    db_session: Session, alembic_cfg: Config
) -> None:
    """0009 adds ops.assistant_feedback, one answer per handoff; downgrade drops it."""

    def tables() -> set[str]:
        rows = db_session.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'ops'"
            )
        ).fetchall()
        db_session.commit()
        return {row[0] for row in rows}

    command.downgrade(alembic_cfg, "0008_handoff_assignment")
    assert "assistant_feedback" not in tables()

    command.upgrade(alembic_cfg, "head")
    assert "assistant_feedback" in tables()
    db_session.execute(
        sa.text(
            "INSERT INTO ops.handoff (id, handoff_ref, session_ref, reason, priority, "
            "department, summary, idempotency_scope) VALUES (gen_random_uuid(), "
            "'hnd_feedbackmigration', 'session-x', 'FRAUD', 'HIGH', "
            "'FRAUD_OPERATIONS', '{}', 'scope')"
        )
    )
    insert_answer = sa.text(
        "INSERT INTO ops.assistant_feedback (id, handoff_id, helpful) "
        "SELECT gen_random_uuid(), id, :helpful FROM ops.handoff "
        "WHERE handoff_ref = 'hnd_feedbackmigration'"
    )
    db_session.execute(insert_answer, {"helpful": True})
    db_session.commit()
    with pytest.raises(sa.exc.IntegrityError):
        db_session.execute(insert_answer, {"helpful": False})
    db_session.rollback()

    command.downgrade(alembic_cfg, "0008_handoff_assignment")
    assert "assistant_feedback" not in tables()
    db_session.execute(
        sa.text("DELETE FROM ops.handoff WHERE handoff_ref = 'hnd_feedbackmigration'")
    )
    db_session.commit()


def test_alembic_0010_handoff_decisions_down_and_up(
    db_session: Session, alembic_cfg: Config
) -> None:
    """0010 allows CLOSED and adds the decision columns; downgrade refuses if closed."""

    def columns() -> set[str]:
        rows = db_session.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'ops' AND table_name = 'handoff'"
            )
        ).fetchall()
        db_session.commit()
        return {row[0] for row in rows}

    decision_columns = {"outcome", "outcome_reason", "closed_by", "closed_at"}
    insert = sa.text(
        "INSERT INTO ops.handoff (id, handoff_ref, session_ref, reason, priority, "
        "department, status, summary, idempotency_scope) VALUES (gen_random_uuid(), "
        ":ref, 'session-y', 'DISPUTE_CLAIM', 'HIGH', 'DISPUTES', :status, '{}', "
        "'scope')"
    )

    command.downgrade(alembic_cfg, "0009_assistant_feedback")
    assert not decision_columns & columns()
    with pytest.raises(sa.exc.IntegrityError):
        db_session.execute(insert, {"ref": "hnd_old_closed", "status": "CLOSED"})
    db_session.rollback()

    command.upgrade(alembic_cfg, "head")
    assert decision_columns <= columns()
    db_session.execute(insert, {"ref": "hnd_new_closed", "status": "CLOSED"})
    db_session.execute(
        sa.text(
            "UPDATE ops.handoff SET outcome = 'APPROVED' "
            "WHERE handoff_ref = 'hnd_new_closed'"
        )
    )
    db_session.commit()
    with pytest.raises(sa.exc.IntegrityError):
        db_session.execute(
            sa.text(
                "UPDATE ops.handoff SET outcome = 'MAYBE' "
                "WHERE handoff_ref = 'hnd_new_closed'"
            )
        )
    db_session.rollback()

    # A closed case cannot survive the old constraint: the downgrade says so.
    with pytest.raises(RuntimeError, match="closed handoff"):
        command.downgrade(alembic_cfg, "0009_assistant_feedback")
    db_session.execute(
        sa.text("DELETE FROM ops.handoff WHERE handoff_ref = 'hnd_new_closed'")
    )
    db_session.commit()
    command.downgrade(alembic_cfg, "0009_assistant_feedback")
    assert not decision_columns & columns()
    command.upgrade(alembic_cfg, "head")


def test_alembic_0011_handoff_identity_attempt_down_and_up(
    db_session: Session, alembic_cfg: Config
) -> None:
    """0011 adds the gated handoff reasons; rows saved before it take the default."""
    column = "handoff_reasons_requiring_identity_attempt"
    command.downgrade(alembic_cfg, "0010_handoff_decisions")
    assert column not in _policy_columns(db_session)
    db_session.execute(sa.text("DELETE FROM config.policy_config"))
    db_session.execute(
        sa.text(
            "INSERT INTO config.policy_config (version, is_active) VALUES (1, true)"
        )
    )
    db_session.commit()

    command.upgrade(alembic_cfg, "head")
    assert column in _policy_columns(db_session)
    stored = db_session.execute(
        sa.text(f"SELECT {column} FROM config.policy_config WHERE version = 1")
    ).scalar_one()
    assert stored == [
        "DISPUTE_CLAIM",
        "UNRECOGNIZED_TRANSACTION",
        "VERIFICATION_FAILED",
    ]
    # Leave no open transaction: it would hold a lock the next migration waits on.
    db_session.execute(sa.text("DELETE FROM config.policy_config"))
    db_session.commit()
