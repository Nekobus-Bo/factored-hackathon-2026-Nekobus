from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

import fakeredis
import pytest
import sqlalchemy as sa
from banking_core.api import admin_router, validate_admin_api_settings
from banking_core.api.routes_admin import (
    DEVELOPMENT_ADMIN_TOKEN,
    get_attempt_limit_store,
)
from banking_core.control.attempt_limits import AttemptLimitStore
from banking_core.control.loader import load_policy_config, save_policy_config
from banking_core.crypto import RecordEncryptor, compute_blind_index, get_master_key
from banking_core.db.session import get_session_maker
from banking_core.identity.config import IdentityConfig
from banking_core.main import app, mount_admin_router_if_enabled
from banking_core.models.config import PolicyConfigRecord
from banking_core.models.core_bank import Account, Card, Customer
from banking_core.models.enums import DocumentType
from banking_core.seed.fixtures import create_scenario_fixtures
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
ADMIN_TOKEN = "test-admin-token"
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture
def limit_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def admin_client(
    monkeypatch: pytest.MonkeyPatch, limit_redis: fakeredis.FakeRedis
) -> Iterator[TestClient]:
    monkeypatch.setenv("ADMIN_API_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("BLIND_INDEX_SALT", "admin-api-test-salt")
    test_app = FastAPI()
    test_app.include_router(admin_router)
    store = AttemptLimitStore(redis_client=limit_redis)
    test_app.dependency_overrides[get_attempt_limit_store] = lambda: store
    with TestClient(test_app) as client:
        yield client


def _audit_count(action: str) -> int:
    with get_session_maker()() as session:
        return session.execute(
            sa.text("SELECT count(*) FROM ops.audit_log WHERE action = :action"),
            {"action": action},
        ).scalar_one()


def _active_policy_version() -> int:
    with get_session_maker()() as session:
        record = session.execute(
            sa.select(PolicyConfigRecord)
            .where(PolicyConfigRecord.is_active.is_(True))
            .order_by(PolicyConfigRecord.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        return record.version if record is not None else 0


def _seed_demo_card() -> tuple[UUID, UUID, UUID, bool, bool, bool]:
    fixtures = create_scenario_fixtures()
    customer_data = fixtures.customers[0]
    account_data = fixtures.accounts[0]
    card_data = fixtures.cards[0]
    customer_id = UUID(str(customer_data["id"]))
    account_id = UUID(str(account_data["id"]))
    card_id = UUID(str(card_data["id"]))
    created_customer = False
    created_account = False
    created_card = False

    with get_session_maker()() as session:
        if session.get(Card, card_id) is None:
            if session.get(Customer, customer_id) is None:
                document_type = DocumentType(str(customer_data["document_type"]))
                document_number = str(customer_data["document_number"])
                email = str(customer_data["email"])
                phone = str(customer_data["phone"])
                master_key = get_master_key(
                    "test-only-admin-api-master-key-0123456789abcdef"
                )
                customer_encryptor = RecordEncryptor(
                    schema="core_bank",
                    table="customer",
                    record_id=customer_id,
                    master_key=master_key,
                )
                customer = Customer(
                    id=customer_id,
                    document_type=document_type,
                    document_number_enc=customer_encryptor.encrypt(
                        "document_number_enc", document_number
                    ),
                    document_number_bidx=compute_blind_index(
                        value=document_number,
                        field_name="document_number",
                        salt="admin-api-test-salt",
                        document_type=document_type,
                    ),
                    full_name_enc=customer_encryptor.encrypt(
                        "full_name_enc", str(customer_data["full_name"])
                    ),
                    email_enc=customer_encryptor.encrypt("email_enc", email),
                    email_bidx=compute_blind_index(
                        value=email,
                        field_name="email",
                        salt="admin-api-test-salt",
                    ),
                    phone_enc=customer_encryptor.encrypt("phone_enc", phone),
                    phone_bidx=compute_blind_index(
                        value=phone,
                        field_name="phone",
                        salt="admin-api-test-salt",
                    ),
                    birth_date_enc=customer_encryptor.encrypt(
                        "birth_date_enc", str(customer_data["birth_date"])
                    ),
                    preferred_locale=str(customer_data["preferred_locale"]),
                    registered_otp_channel=str(customer_data["registered_otp_channel"]),
                    data_origin="synthetic",
                    created_at=datetime.fromisoformat(str(customer_data["created_at"])),
                    source_ref="tests/test_admin_api.py",
                    loaded_at=datetime.now(UTC),
                    code_version="test",
                )
                session.add(customer)
                created_customer = True

            if session.get(Account, account_id) is None:
                account = Account(
                    id=account_id,
                    customer_id=customer_id,
                    type=str(account_data["type"]),
                    currency=str(account_data["currency"]),
                    available_balance_minor=int(
                        account_data["available_balance_minor"]
                    ),
                    ledger_balance_minor=int(account_data["ledger_balance_minor"]),
                    status=str(account_data["status"]),
                    data_origin="synthetic",
                    source_ref="tests/test_admin_api.py",
                    loaded_at=datetime.now(UTC),
                    code_version="test",
                )
                session.add(account)
                created_account = True

            card_encryptor = RecordEncryptor(
                schema="core_bank",
                table="card",
                record_id=card_id,
                master_key=get_master_key(
                    "test-only-admin-api-master-key-0123456789abcdef"
                ),
            )
            card = Card(
                id=card_id,
                account_id=account_id,
                card_ref=str(card_data["card_ref"]),
                pan_last4=str(card_data["pan_last4"]),
                pan_enc=card_encryptor.encrypt("pan_enc", str(card_data["pan"])),
                brand=str(card_data["brand"]),
                status=str(card_data["status"]),
                blocked_at=None,
                blocked_reason=None,
                card_type=None,
                expiry_month=None,
                expiry_year=None,
                data_origin="synthetic",
                source_ref="tests/test_admin_api.py",
                loaded_at=datetime.now(UTC),
                code_version="test",
            )
            session.add(card)
            created_card = True
            session.commit()

    return (
        card_id,
        customer_id,
        account_id,
        created_card,
        created_account,
        created_customer,
    )


def _cleanup_demo_card(
    card_id: UUID,
    customer_id: UUID,
    account_id: UUID,
    created_card: bool,
    created_account: bool,
    created_customer: bool,
) -> None:
    with get_session_maker()() as session:
        card = session.get(Card, card_id)
        if card is not None:
            if created_card:
                session.delete(card)
            else:
                card.status = "ACTIVE"
                card.blocked_at = None
                card.blocked_reason = None
        account = session.get(Account, account_id)
        if created_account and account is not None:
            session.delete(account)
        customer = session.get(Customer, customer_id)
        if created_customer and customer is not None:
            session.delete(customer)
        session.commit()


def test_admin_requests_require_a_valid_bearer_token(
    admin_client: TestClient,
) -> None:
    without_token = admin_client.get("/v1/admin/policy-config")
    wrong_token = admin_client.get(
        "/v1/admin/policy-config",
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert without_token.status_code == 401
    assert wrong_token.status_code == 401


def test_admin_router_is_not_mounted_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_ENABLED", "false")
    test_app = FastAPI()
    mount_admin_router_if_enabled(test_app)

    assert not any(route.path.startswith("/v1/admin") for route in test_app.routes)


def test_startup_fails_when_admin_api_has_no_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_ENABLED", "true")
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="ADMIN_API_TOKEN is required"):
        with TestClient(app):
            pass


@pytest.mark.parametrize(
    "app_env", ["production", "Production", " PRODUCTION "], ids=repr
)
@pytest.mark.parametrize(
    "token",
    [DEVELOPMENT_ADMIN_TOKEN, f" {DEVELOPMENT_ADMIN_TOKEN}\n"],
    ids=["exact", "padded"],
)
def test_startup_refuses_the_development_admin_token_in_production(
    monkeypatch: pytest.MonkeyPatch, app_env: str, token: str
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_TOKEN", token)

    with pytest.raises(RuntimeError, match="public development token"):
        with TestClient(app):
            pass


@pytest.mark.parametrize("token", ["", "   "], ids=["empty", "blank"])
def test_startup_refuses_an_empty_admin_token_in_production(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_TOKEN", token)

    with pytest.raises(RuntimeError, match="ADMIN_API_TOKEN is required"):
        validate_admin_api_settings()


@pytest.mark.parametrize(
    ("app_env", "enabled", "token"),
    [
        ("development", "true", DEVELOPMENT_ADMIN_TOKEN),
        (None, "true", DEVELOPMENT_ADMIN_TOKEN),
        ("production", "true", "a-real-secret-from-the-platform"),
        ("production", "false", DEVELOPMENT_ADMIN_TOKEN),
        ("production", "false", ""),
    ],
    ids=[
        "development-accepts-the-development-token",
        "unset-app-env-is-development",
        "production-accepts-its-own-secret",
        "production-with-the-api-off-uses-no-token",
        "production-with-the-api-off-and-no-token",
    ],
)
def test_startup_accepts_the_admin_settings_that_are_safe(
    monkeypatch: pytest.MonkeyPatch, app_env: str | None, enabled: str, token: str
) -> None:
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("ADMIN_API_ENABLED", enabled)
    monkeypatch.setenv("ADMIN_API_TOKEN", token)

    validate_admin_api_settings()


def test_compose_default_admin_token_is_the_one_production_refuses() -> None:
    """If the compose default drifts, the production guard silently stops matching."""
    compose = (REPO_ROOT / "infra/compose/docker-compose.yml").read_text()
    defaults = re.findall(r"ADMIN_API_TOKEN: \$\{ADMIN_API_TOKEN:-([^}]*)\}", compose)

    # banking-core, and web-backoffice, which sends the token banking-core expects.
    assert defaults == [DEVELOPMENT_ADMIN_TOKEN, DEVELOPMENT_ADMIN_TOKEN]


@pytest.mark.usefixtures("db_engine")
def test_invalid_policy_update_returns_422_without_new_version(
    admin_client: TestClient,
) -> None:
    current = admin_client.get("/v1/admin/policy-config", headers=ADMIN_HEADERS)
    assert current.status_code == 200
    version = current.json()["version"]

    response = admin_client.put(
        "/v1/admin/policy-config",
        headers=ADMIN_HEADERS,
        json={
            "amount_mode": "flag",
            "thresholds_minor": {"USD": 0},
        },
    )

    assert response.status_code == 422
    assert _active_policy_version() == version


@pytest.mark.usefixtures("db_engine")
def test_policy_update_is_versioned_live_and_audited(
    admin_client: TestClient,
) -> None:
    initial = admin_client.get("/v1/admin/policy-config", headers=ADMIN_HEADERS)
    assert initial.status_code == 200
    original = initial.json()
    if original["amount_mode"] != "flag":
        setup = admin_client.put(
            "/v1/admin/policy-config",
            headers=ADMIN_HEADERS,
            json={
                "amount_mode": "flag",
                "thresholds_minor": original["thresholds_minor"],
            },
        )
        assert setup.status_code == 200
        original = admin_client.get(
            "/v1/admin/policy-config", headers=ADMIN_HEADERS
        ).json()

    audit_before = _audit_count("admin.policy_config.updated")
    response = admin_client.put(
        "/v1/admin/policy-config",
        headers=ADMIN_HEADERS,
        json={
            "amount_mode": "block",
            "thresholds_minor": original["thresholds_minor"],
        },
    )
    try:
        assert response.status_code == 200
        updated = response.json()
        assert updated["amount_mode"] == "block"
        assert updated["version"] == original["version"] + 1
        assert _active_policy_version() == updated["version"]
        assert _audit_count("admin.policy_config.updated") == audit_before + 1
        assert load_policy_config().amount_mode == "block"

        with get_session_maker()() as session:
            entry = session.execute(
                sa.text(
                    "SELECT actor_type, actor_ref, payload "
                    "FROM ops.audit_log "
                    "WHERE action = 'admin.policy_config.updated' "
                    "ORDER BY id DESC LIMIT 1"
                )
            ).one()
        assert entry.actor_type == "agent"
        assert entry.actor_ref == "admin"
        assert entry.payload["version"] == updated["version"]
        assert entry.payload["before"]["amount_mode"] == "flag"
        assert entry.payload["after"]["amount_mode"] == "block"
    finally:
        restored = admin_client.put(
            "/v1/admin/policy-config",
            headers=ADMIN_HEADERS,
            json={
                "amount_mode": original["amount_mode"],
                "thresholds_minor": original["thresholds_minor"],
            },
        )
        assert restored.status_code == 200


@pytest.mark.usefixtures("db_engine")
def test_policy_update_keeps_the_attempt_limits(admin_client: TestClient) -> None:
    """The admin PUT edits the amount policy only: other saved fields carry over."""
    current = load_policy_config()
    custom = current.model_copy(
        update={
            "customer_otp_max_failures": 4,
            "customer_otp_lock_seconds": 900,
            "document_match_max_failures": 7,
        }
    )
    try:
        with get_session_maker()() as session:
            save_policy_config(custom, session=session)

        response = admin_client.put(
            "/v1/admin/policy-config",
            headers=ADMIN_HEADERS,
            json={
                "amount_mode": "block",
                "thresholds_minor": current.thresholds_minor,
            },
        )

        assert response.status_code == 200
        saved = load_policy_config()
        assert saved.amount_mode == "block"
        assert saved.customer_otp_max_failures == 4
        assert saved.customer_otp_lock_seconds == 900
        assert saved.document_match_max_failures == 7
    finally:
        with get_session_maker()() as session:
            save_policy_config(current, session=session)


@pytest.mark.usefixtures("db_engine")
def test_policy_update_can_lower_or_drop_the_default_currency_threshold(
    admin_client: TestClient,
) -> None:
    """The threshold of the default currency (COP) follows the request too.

    A stale single-threshold copy of the current config used to win over the
    requested map, so the demo could not lower the COP threshold live.
    """
    original = admin_client.get("/v1/admin/policy-config", headers=ADMIN_HEADERS).json()
    lowered = {"COP": 20000000, "USD": 10000, "BRL": 30000, "EUR": 50000}
    without_default = {"USD": 10000, "EUR": 50000}

    def put(thresholds: dict[str, int]) -> dict[str, int]:
        response = admin_client.put(
            "/v1/admin/policy-config",
            headers=ADMIN_HEADERS,
            json={"amount_mode": "block", "thresholds_minor": thresholds},
        )
        assert response.status_code == 200
        assert response.json()["thresholds_minor"] == thresholds
        return load_policy_config().thresholds_minor

    try:
        assert put(lowered) == lowered
        assert put(without_default) == without_default
        assert put(lowered) == lowered
    finally:
        restored = admin_client.put(
            "/v1/admin/policy-config",
            headers=ADMIN_HEADERS,
            json={
                "amount_mode": original["amount_mode"],
                "thresholds_minor": original["thresholds_minor"],
            },
        )
        assert restored.status_code == 200


@pytest.mark.usefixtures("db_engine")
def test_demo_reset_restores_fixture_card_and_audits_change(
    admin_client: TestClient,
) -> None:
    (
        card_id,
        customer_id,
        account_id,
        created_card,
        created_account,
        created_customer,
    ) = _seed_demo_card()
    try:
        with get_session_maker()() as session:
            card = session.get(Card, card_id)
            assert card is not None
            card.status = "BLOCKED"
            card.blocked_at = datetime.now(UTC)
            card.blocked_reason = "SUSPICIOUS_ACTIVITY"
            session.commit()

        audit_before = _audit_count("admin.demo.fixtures.reset")
        response = admin_client.post(
            "/v1/admin/demo/reset-fixtures", headers=ADMIN_HEADERS
        )

        assert response.status_code == 200
        assert response.json()["cards_reset"] >= 1
        assert response.json()["cards_changed"] >= 1
        assert _audit_count("admin.demo.fixtures.reset") == audit_before + 1
        with get_session_maker()() as session:
            restored = session.get(Card, card_id)
            assert restored is not None
            status_value = (
                restored.status.value
                if isinstance(restored.status, Enum)
                else restored.status
            )
            assert status_value == "ACTIVE"
            assert restored.blocked_at is None
            assert restored.blocked_reason is None
    finally:
        _cleanup_demo_card(
            card_id,
            customer_id,
            account_id,
            created_card,
            created_account,
            created_customer,
        )


@pytest.mark.usefixtures("db_engine")
def test_demo_reset_forgets_the_attempt_limits_of_fixture_customers_only(
    admin_client: TestClient, limit_redis: fakeredis.FakeRedis
) -> None:
    fixtures = create_scenario_fixtures().customers
    demo = fixtures[0]
    demo_id = str(demo["id"])
    demo_number = str(demo["document_number"])
    document_type = DocumentType(str(demo["document_type"]))
    fixture_keys = {
        f"limit:customer:{demo_id}:otp_failures",
        f"limit:customer:{demo_id}:otp_lock",
    }
    for candidate in IdentityConfig.from_env().resolve_equivalent_document_types(
        document_type
    ):
        bidx = compute_blind_index(
            demo_number,
            "document_number",
            "admin-api-test-salt",
            document_type=candidate,
        )
        fixture_keys.add(f"limit:document:{bidx}:match_failures")
    stranger_customer = "0d3f2a7c-88b1-4d55-8a4e-5b2c7d1e9f22"
    stranger_document = f"limit:document:{'d' * 64}:match_failures"
    for key in (*fixture_keys, f"limit:customer:{stranger_customer}:otp_lock"):
        limit_redis.set(key, "1")
    limit_redis.set(stranger_document, "7")

    response = admin_client.post("/v1/admin/demo/reset-fixtures", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["attempt_limits_cleared"] == len(fixture_keys)
    assert set(limit_redis.keys("limit:*")) == {
        f"limit:customer:{stranger_customer}:otp_lock",
        stranger_document,
    }


def test_demo_reset_is_denied_in_production_without_override(
    admin_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_RESET_ENABLED", "false")

    response = admin_client.post("/v1/admin/demo/reset-fixtures", headers=ADMIN_HEADERS)

    assert response.status_code == 403
