"""POST /v1/sessions/{id}/feedback: one answer per handoff, audited (ADR-0017)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from banking_core.api.routes_sessions import router as sessions_router
from banking_core.audit.service import verify_chain
from banking_core.db.session import get_session_maker
from banking_core.handoff.feedback import FEEDBACK_ACTION
from banking_core.models.ops import Handoff
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

SESSION = "sess_" + "a" * 32
OTHER_SESSION = "sess_" + "b" * 32
T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _clear_handoffs() -> None:
    with get_session_maker()() as session:
        session.execute(sa.text("DELETE FROM ops.handoff"))
        session.commit()


def _add_handoff(
    ref: str, *, session_ref: str = SESSION, created_at: datetime = T0
) -> None:
    with get_session_maker()() as session:
        session.add(
            Handoff(
                handoff_ref=ref,
                session_ref=session_ref,
                reason="DISPUTE_CLAIM",
                priority="NORMAL",
                department="DISPUTES",
                status="QUEUED",
                summary={"verified_facts": {}},
                idempotency_scope=session_ref,
                created_at=created_at,
            )
        )
        session.commit()


def _answers() -> list[tuple[str, bool]]:
    with get_session_maker()() as session:
        rows = session.execute(
            sa.text(
                "SELECT h.handoff_ref, f.helpful FROM ops.assistant_feedback f "
                "JOIN ops.handoff h ON h.id = f.handoff_id ORDER BY h.handoff_ref"
            )
        )
        return [(row[0], row[1]) for row in rows]


def _audits() -> list[sa.Row[Any]]:
    with get_session_maker()() as session:
        return list(
            session.execute(
                sa.text(
                    "SELECT actor_type, actor_ref, decision, reason_code, payload "
                    "FROM ops.audit_log WHERE action = :action ORDER BY id"
                ),
                {"action": FEEDBACK_ACTION},
            )
        )


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    _clear_handoffs()
    app = FastAPI()
    app.include_router(sessions_router)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        _clear_handoffs()


def _send(client: TestClient, body: Any, session_id: str = SESSION) -> Any:
    return client.post(f"/v1/sessions/{session_id}/feedback", json=body)


def test_an_answer_after_a_handoff_is_stored_audited_and_read_back(
    client: TestClient,
) -> None:
    _add_handoff("hnd_feedbackone")
    response = _send(client, {"helpful": True})
    assert response.status_code == 200
    body = response.json()
    assert body["handoff_ref"] == "hnd_feedbackone"
    assert body["helpful"] is True
    assert datetime.fromisoformat(body["recorded_at"]).tzinfo is not None
    assert _answers() == [("hnd_feedbackone", True)]

    [audit] = _audits()
    assert (audit.actor_type, audit.actor_ref, audit.decision, audit.reason_code) == (
        "customer_session",
        SESSION,
        "allowed",
        None,
    )
    assert audit.payload == {"handoff_ref": "hnd_feedbackone", "helpful": True}
    with get_session_maker()() as session:
        valid, _total, _, broken_id, error = verify_chain(session)
    assert (valid, broken_id, error) == (True, None, None)


def test_no_handoff_no_answer(client: TestClient) -> None:
    response = _send(client, {"helpful": False})
    assert response.status_code == 409
    assert response.json() == {"detail": "no_handoff"}
    assert _answers() == []
    assert _audits() == []


def test_the_same_answer_again_changes_nothing(client: TestClient) -> None:
    _add_handoff("hnd_feedbacktwice")
    first = _send(client, {"helpful": False})
    second = _send(client, {"helpful": False})
    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json() == first.json()
    assert _answers() == [("hnd_feedbacktwice", False)]
    assert len(_audits()) == 1


def test_a_different_answer_is_refused_and_the_first_stands(client: TestClient) -> None:
    _add_handoff("hnd_feedbackflip")
    assert _send(client, {"helpful": True}).status_code == 200
    response = _send(client, {"helpful": False})
    assert response.status_code == 409
    assert response.json() == {"detail": "already_answered"}
    assert _answers() == [("hnd_feedbackflip", True)]
    assert len(_audits()) == 1


def test_the_newest_handoff_of_the_session_is_the_one_rated(client: TestClient) -> None:
    _add_handoff("hnd_feedbackolder", created_at=T0)
    _add_handoff("hnd_feedbacknewer", created_at=T0 + timedelta(hours=1))
    assert _send(client, {"helpful": True}).json()["handoff_ref"] == "hnd_feedbacknewer"
    assert _answers() == [("hnd_feedbacknewer", True)]


def test_a_session_cannot_rate_another_sessions_handoff(client: TestClient) -> None:
    _add_handoff("hnd_feedbackother", session_ref=OTHER_SESSION)
    assert _send(client, {"helpful": True}).status_code == 409
    assert _answers() == []


@pytest.mark.parametrize(
    ("body", "session_id"),
    [
        ({"helpful": "yes"}, SESSION),
        ({"helpful": 1}, SESSION),
        ({"helpful": True, "comment": "great"}, SESSION),
        ({}, SESSION),
        ({"helpful": True}, "not-a-session"),
    ],
)
def test_the_body_and_the_session_id_are_strict(
    client: TestClient, body: Any, session_id: str
) -> None:
    _add_handoff("hnd_feedbackstrict")
    assert _send(client, body, session_id).status_code == 422
    assert _answers() == []


def test_deleting_a_handoff_deletes_its_answer(client: TestClient) -> None:
    _add_handoff("hnd_feedbackcascade")
    assert _send(client, {"helpful": True}).status_code == 200
    _clear_handoffs()
    assert _answers() == []
