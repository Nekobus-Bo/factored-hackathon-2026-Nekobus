"""Admin API for the versioned tool policy: /v1/admin/tool-policy and the demo reset."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import Any

import fakeredis
import pytest
import sqlalchemy as sa
from banking_core.api import admin_router, routes_sessions, routes_tools, tools_router
from banking_core.api.dispatcher import ToolDispatcher
from banking_core.api.routes_admin import get_attempt_limit_store
from banking_core.api.routes_sessions import get_session_store, set_session_store
from banking_core.api.routes_tools import set_dispatcher
from banking_core.control.attempt_limits import AttemptLimitStore
from banking_core.control.config import DatabaseControlConfigRepository
from banking_core.control.session import RedisSessionStore, SessionState
from banking_core.db import get_db
from banking_core.db.session import get_session_maker
from banking_core.identity import OtpChallengeStore, get_dev_sink
from banking_core.seed.curated import load_curated_data
from banking_core.seed.fixtures import create_scenario_fixtures
from banking_core.seed.staging import (
    StagingAccount,
    StagingCard,
    StagingCustomer,
    StagingDataset,
    StagingTransaction,
)
from contracts.envelope import VerificationState
from contracts.tools import CODE_FLOOR, TOOL_CATALOG
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ADMIN_TOKEN = "test-admin-token"
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
TEST_MASTER_KEY = "00" * 32
TEST_BLIND_INDEX_SALT = "tool-policy-api-test-salt"
POLICY = "/v1/admin/tool-policy"
AUDIT_ACTION = "admin.tool_policy.updated"


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def client(
    db_engine: sa.Engine,
    fake_redis: fakeredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("ADMIN_API_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("MASTER_KEY", TEST_MASTER_KEY)
    monkeypatch.setenv("BLIND_INDEX_SALT", TEST_BLIND_INDEX_SALT)
    monkeypatch.delenv("POLICY_SEED_DISABLED_TOOLS", raising=False)

    previous = (routes_sessions._session_store, routes_tools._dispatcher)
    session_store = RedisSessionStore(redis_client=fake_redis, default_ttl=3600)
    set_session_store(session_store)
    dev_sink = get_dev_sink()
    dev_sink.clear()
    # The dispatcher reads the tool policy from the database, like production.
    set_dispatcher(
        ToolDispatcher(
            config_repo=DatabaseControlConfigRepository(),
            session_store=session_store,
            delivery_port=dev_sink,
            challenge_store=OtpChallengeStore(redis_client=fake_redis),
        )
    )
    test_app = FastAPI()
    test_app.include_router(admin_router)
    test_app.include_router(tools_router)
    limits = AttemptLimitStore(redis_client=fake_redis)

    def override_get_db() -> Generator[Session, None, None]:
        with get_session_maker()() as db:
            yield db

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_session_store] = lambda: session_store
    test_app.dependency_overrides[get_attempt_limit_store] = lambda: limits
    try:
        with TestClient(test_app) as test_client:
            yield test_client
    finally:
        dev_sink.clear()
        routes_sessions._session_store, routes_tools._dispatcher = previous


def _get(client: TestClient) -> dict[str, Any]:
    response = client.get(POLICY, headers=ADMIN_HEADERS)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _put(client: TestClient, tools: dict[str, Any]) -> Any:
    return client.put(POLICY, headers=ADMIN_HEADERS, json={"tools": tools})


def _audit(action: str = AUDIT_ACTION) -> list[sa.Row]:  # type: ignore[type-arg]
    with get_session_maker()() as session:
        return list(
            session.execute(
                sa.text(
                    "SELECT actor_type, actor_ref, decision, payload "
                    "FROM ops.audit_log WHERE action = :action ORDER BY id"
                ),
                {"action": action},
            )
        )


@pytest.mark.usefixtures("db_session")
def test_tool_policy_requires_the_admin_token(client: TestClient) -> None:
    for headers in ({}, {"Authorization": "Bearer wrong-token"}):
        assert client.get(POLICY, headers=headers).status_code == 401
        put = client.put(
            POLICY, headers=headers, json={"tools": {"card.list": ["VERIFIED"]}}
        )
        assert put.status_code == 401
    assert _audit() == []


@pytest.mark.usefixtures("db_session")
def test_get_reports_the_seed_and_the_ceiling(client: TestClient) -> None:
    body = _get(client)

    assert body["version"] == 1
    assert body["disabled"] == ["account.get_summary"]
    assert body["tools"]["account.get_summary"] == []
    assert body["tools"]["transaction.list_recent"] == ["VERIFIED"]
    assert set(body["tools"]) == set(TOOL_CATALOG)
    assert body["code_floor"] == {
        name: sorted(state.value for state in states)
        for name, states in CODE_FLOOR.items()
    }
    # Reading is not a change.
    assert _audit() == []


@pytest.mark.usefixtures("db_session")
def test_put_enables_a_tool_as_a_new_audited_version(client: TestClient) -> None:
    response = _put(client, {"account.get_summary": ["VERIFIED"]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == 2
    assert body["disabled"] == []
    assert body["tools"]["account.get_summary"] == ["VERIFIED"]
    assert _get(client) == body
    [entry] = _audit()
    assert (entry.actor_type, entry.actor_ref, entry.decision) == (
        "agent",
        "admin",
        "allowed",
    )
    assert entry.payload == {
        "version": 2,
        "previous_version": 1,
        "source": "admin_api",
        "changes": [
            {"tool": "account.get_summary", "before": [], "after": ["VERIFIED"]}
        ],
    }


@pytest.mark.usefixtures("db_session")
def test_put_changes_only_the_tools_it_names(client: TestClient) -> None:
    before = _get(client)

    body = _put(client, {"card.list": []}).json()

    assert body["disabled"] == ["account.get_summary", "card.list"]
    assert {k: v for k, v in body["tools"].items() if k != "card.list"} == {
        k: v for k, v in before["tools"].items() if k != "card.list"
    }


@pytest.mark.usefixtures("db_session")
def test_put_can_restrict_a_tool_to_fewer_states(client: TestClient) -> None:
    body = _put(client, {"kb.search": ["VERIFIED", "IDENTIFIED", "VERIFIED"]}).json()

    assert body["tools"]["kb.search"] == ["IDENTIFIED", "VERIFIED"]


@pytest.mark.usefixtures("db_session")
def test_put_refuses_to_widen_beyond_the_code_floor(client: TestClient) -> None:
    before = _get(client)

    response = _put(
        client,
        {
            "card.block": ["ANONYMOUS", "VERIFIED"],
            "account.get_summary": ["IDENTIFIED"],
            "card.list": ["VERIFIED"],
        },
    )

    assert response.status_code == 422
    problems = {tuple(item["loc"]): item for item in response.json()["detail"]}
    assert set(problems) == {
        ("body", "tools", "card.block"),
        ("body", "tools", "account.get_summary"),
    }
    block = problems[("body", "tools", "card.block")]
    assert block["type"] == "code_floor_violation"
    assert "'card.block'" in block["msg"] and "ANONYMOUS" in block["msg"]
    assert "Code floor allows ['VERIFIED']" in block["msg"]
    # Not clamped, not partly applied: same version, same matrix, no audit row.
    assert _get(client) == before
    assert _audit() == []


@pytest.mark.usefixtures("db_session")
@pytest.mark.parametrize(
    ("tool", "state"),
    [
        (tool, state)
        for tool, floor in CODE_FLOOR.items()
        for state in VerificationState
        if state not in floor
    ],
)
def test_no_tool_can_be_enabled_in_a_state_outside_its_floor(
    client: TestClient, tool: str, state: VerificationState
) -> None:
    response = _put(client, {tool: [state.value]})

    assert response.status_code == 422, response.text
    assert _get(client)["version"] == 1


@pytest.mark.usefixtures("db_session")
def test_put_rejects_unknown_tools_and_malformed_bodies(client: TestClient) -> None:
    unknown = _put(client, {"card.nuke": ["VERIFIED"]})
    assert unknown.status_code == 422
    assert unknown.json()["detail"][0]["type"] == "unknown_tool"

    for body in (
        {"tools": {"card.list": ["SUPERUSER"]}},
        {"tools": {}},
        {"tools": {"card.list": "VERIFIED"}},
        {"tools": {"card.list": ["VERIFIED"]}, "everything": True},
        {},
    ):
        response = client.put(POLICY, headers=ADMIN_HEADERS, json=body)
        assert response.status_code == 422, body
    assert _get(client)["version"] == 1
    assert _audit() == []


@pytest.mark.usefixtures("db_session")
def test_a_stored_version_beyond_the_floor_is_reported_and_repairable(
    client: TestClient,
) -> None:
    _get(client)  # seeds version 1
    with get_session_maker()() as session:
        session.execute(
            sa.text(
                "UPDATE config.tool_policy SET matrix = "
                "jsonb_set(matrix, '{card.block}', '[\"ANONYMOUS\"]')"
            )
        )
        session.commit()

    broken = client.get(POLICY, headers=ADMIN_HEADERS)
    assert broken.status_code == 500
    assert "card.block" in broken.json()["detail"]

    repaired = _put(client, {"card.block": ["VERIFIED"]})
    assert repaired.status_code == 200
    assert repaired.json()["tools"]["card.block"] == ["VERIFIED"]


def _seed_customer_data(db_session: Session) -> str:
    bundle = create_scenario_fixtures()
    staging = StagingDataset(
        customers=[StagingCustomer.model_validate(c) for c in bundle.customers],
        accounts=[StagingAccount.model_validate(a) for a in bundle.accounts],
        cards=[StagingCard.model_validate(c) for c in bundle.cards],
        transactions=[
            StagingTransaction.model_validate(t) for t in bundle.transactions
        ],
    )
    load_curated_data(
        staging,
        session=db_session,
        master_key=TEST_MASTER_KEY,
        blind_index_salt=TEST_BLIND_INDEX_SALT,
        force=True,
    )
    return str(bundle.customers[0]["id"])


def _call(client: TestClient, session_id: str, tool: str) -> dict[str, Any]:
    response = client.post(
        "/v1/tools/call",
        json={"tool": tool, "version": "1.0", "args": {"include_balances": False}},
        headers={"X-Session-Id": session_id},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_disabled_tool_is_refused_audited_and_enabled_live(
    client: TestClient, db_session: Session, fake_redis: fakeredis.FakeRedis
) -> None:
    """The whole path: admin toggles, the very next tool call follows, no restart."""
    holder_id = _seed_customer_data(db_session)
    try:
        store = RedisSessionStore(redis_client=fake_redis, default_ttl=3600)
        session_id = "sess_tool_policy_live"
        store.save(
            SessionState(
                session_id=session_id,
                state=VerificationState.VERIFIED,
                pinned_holder_id=holder_id,
            )
        )

        refused = _call(client, session_id, "account.get_summary")
        assert refused["status"] == "refused"
        assert refused["reason_code"] == "STATE_NOT_ALLOWED"
        assert refused["data"] is None
        [refusal] = _audit("account.get_summary")
        assert refusal.decision == "refused"
        assert refusal.payload["status"] == "refused"
        assert refusal.payload["details"] == {"flags": ["TOOL_DISABLED"]}

        assert _put(client, {"account.get_summary": ["VERIFIED"]}).status_code == 200
        allowed = _call(client, session_id, "account.get_summary")
        assert allowed["status"] == "ok"
        assert allowed["data"]["accounts"]

        assert _put(client, {"account.get_summary": []}).status_code == 200
        again = _call(client, session_id, "account.get_summary")
        assert again["status"] == "refused"
        assert again["reason_code"] == "STATE_NOT_ALLOWED"
        assert [row.decision for row in _audit("account.get_summary")] == [
            "refused",
            "allowed",
            "refused",
        ]
    finally:
        db_session.rollback()
        db_session.execute(
            sa.text(
                "TRUNCATE TABLE ops.handoff, core_bank.transaction, core_bank.card, "
                "core_bank.account, core_bank.customer CASCADE"
            )
        )
        db_session.commit()


@pytest.mark.usefixtures("db_session")
def test_an_enabled_tool_is_still_refused_before_verification(
    client: TestClient, fake_redis: fakeredis.FakeRedis
) -> None:
    _put(client, {"account.get_summary": ["VERIFIED"]})
    store = RedisSessionStore(redis_client=fake_redis, default_ttl=3600)
    store.save(SessionState(session_id="sess_anon", state=VerificationState.ANONYMOUS))

    refused = _call(client, "sess_anon", "account.get_summary")

    assert refused["status"] == "refused"
    assert refused["reason_code"] == "STATE_NOT_ALLOWED"
    [row] = _audit("account.get_summary")
    assert row.payload["details"] == {"flags": ["STATE_ANONYMOUS_NOT_PERMITTED"]}


@pytest.mark.usefixtures("db_session")
def test_demo_reset_restores_the_seed_tool_policy(client: TestClient) -> None:
    _put(client, {"account.get_summary": ["VERIFIED"], "card.list": []})
    assert _get(client)["version"] == 2

    reset = client.post("/v1/admin/demo/reset-fixtures", headers=ADMIN_HEADERS)

    assert reset.status_code == 200, reset.text
    assert reset.json()["tool_policy_changed"] is True
    assert reset.json()["tool_policy_version"] == 3
    restored = _get(client)
    assert restored["version"] == 3
    assert restored["disabled"] == ["account.get_summary"]
    assert restored["tools"]["card.list"] == ["VERIFIED"]
    payloads = [row.payload for row in _audit()]
    assert payloads[-1]["source"] == "demo_reset"
    assert {c["tool"] for c in payloads[-1]["changes"]} == {
        "account.get_summary",
        "card.list",
    }
    [reset_audit] = _audit("admin.demo.fixtures.reset")
    assert reset_audit.payload["tool_policy_version"] == 3
    assert reset_audit.payload["tool_policy_changed"] is True


@pytest.mark.usefixtures("db_session")
def test_demo_reset_at_the_seed_writes_no_new_version(client: TestClient) -> None:
    first = client.post("/v1/admin/demo/reset-fixtures", headers=ADMIN_HEADERS)
    second = client.post("/v1/admin/demo/reset-fixtures", headers=ADMIN_HEADERS)

    for reset in (first, second):
        assert reset.status_code == 200, reset.text
        assert reset.json()["tool_policy_changed"] is False
        assert reset.json()["tool_policy_version"] == 1
    assert _audit() == []


@pytest.mark.usefixtures("db_session")
def test_demo_reset_follows_the_seed_variable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLICY_SEED_DISABLED_TOOLS", "")
    reset = client.post("/v1/admin/demo/reset-fixtures", headers=ADMIN_HEADERS)

    assert reset.status_code == 200
    assert reset.json()["tool_policy_version"] == 1  # nothing before it: seeded as is
    assert _get(client)["disabled"] == []
