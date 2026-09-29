"""GET /v1/sessions/{id}/simulated-inbox: scoping, expiry, simulated-only gate."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from banking_core.api import get_session_store
from banking_core.control.session import RedisSessionStore
from banking_core.identity import SimulatedInbox, set_simulated_inbox
from banking_core.main import app
from fastapi.testclient import TestClient

START = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def inbox(clock: Clock) -> Iterator[SimulatedInbox]:
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisSessionStore(redis_client=redis_client, default_ttl=3600)
    simulated = SimulatedInbox(redis_client=redis_client, clock=clock)
    app.dependency_overrides[get_session_store] = lambda: store
    set_simulated_inbox(simulated)
    yield simulated
    app.dependency_overrides.clear()
    set_simulated_inbox(None)


@pytest.fixture
def client(inbox: SimulatedInbox, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("OTP_CHANNEL_MODE", raising=False)
    return TestClient(app)


def new_session(client: TestClient) -> str:
    session_id: str = client.post("/v1/sessions").json()["session_id"]
    return session_id


def deliver(
    inbox: SimulatedInbox,
    session_id: str,
    challenge_id: str,
    code: str,
    ttl_seconds: int = 300,
) -> None:
    inbox.deliver(
        session_id=session_id,
        challenge_id=challenge_id,
        channel="EMAIL",
        destination_masked="d***@example.com",
        code=code,
        ttl_seconds=ttl_seconds,
    )


def inbox_url(session_id: str) -> str:
    return f"/v1/sessions/{session_id}/simulated-inbox"


def test_a_session_without_messages_has_an_empty_inbox(client: TestClient) -> None:
    response = client.get(inbox_url(new_session(client)))

    assert response.status_code == 200
    assert response.json() == {"messages": []}


def test_the_inbox_lists_the_sessions_messages_newest_first(
    client: TestClient, inbox: SimulatedInbox, clock: Clock
) -> None:
    session_id = new_session(client)
    deliver(inbox, session_id, "chal_first", "111111")
    clock.now += timedelta(seconds=20)
    deliver(inbox, session_id, "chal_second", "222222")

    response = client.get(inbox_url(session_id))

    assert response.status_code == 200
    body = response.json()
    assert [m["code"] for m in body["messages"]] == ["222222", "111111"]
    assert body["messages"][0] == {
        "challenge_id": "chal_second",
        "channel": "EMAIL",
        "destination_masked": "d***@example.com",
        "code": "222222",
        "created_at": "2026-09-29T12:00:20Z",
        "expires_at": "2026-09-29T12:05:20Z",
    }


def test_the_response_is_not_cacheable(
    client: TestClient, inbox: SimulatedInbox
) -> None:
    session_id = new_session(client)
    deliver(inbox, session_id, "chal_a1", "482913")

    response = client.get(inbox_url(session_id))

    assert response.headers["cache-control"] == "no-store"


def test_expired_messages_are_not_returned(
    client: TestClient, inbox: SimulatedInbox, clock: Clock
) -> None:
    session_id = new_session(client)
    deliver(inbox, session_id, "chal_short", "111111", ttl_seconds=60)
    deliver(inbox, session_id, "chal_long", "222222", ttl_seconds=300)

    clock.now += timedelta(seconds=61)

    codes = [m["code"] for m in client.get(inbox_url(session_id)).json()["messages"]]
    assert codes == ["222222"]

    clock.now += timedelta(seconds=300)

    assert client.get(inbox_url(session_id)).json() == {"messages": []}


def test_one_session_cannot_read_another_sessions_code(
    client: TestClient, inbox: SimulatedInbox
) -> None:
    mine = new_session(client)
    theirs = new_session(client)
    deliver(inbox, theirs, "chal_theirs", "999999")

    response = client.get(inbox_url(mine))

    assert response.status_code == 200
    assert response.json() == {"messages": []}
    assert "999999" not in response.text
    assert client.get(inbox_url(theirs)).json()["messages"][0]["code"] == "999999"


def test_an_unknown_session_is_a_404_even_if_an_inbox_exists_for_its_id(
    client: TestClient, inbox: SimulatedInbox
) -> None:
    deliver(inbox, "sess_ghost", "chal_ghost", "999999")

    response = client.get(inbox_url("sess_ghost"))

    assert response.status_code == 404
    assert "999999" not in response.text


def test_the_inbox_does_not_exist_when_delivery_is_not_simulated(
    client: TestClient, inbox: SimulatedInbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = new_session(client)
    deliver(inbox, session_id, "chal_a1", "482913")
    monkeypatch.setenv("OTP_CHANNEL_MODE", "smtp")

    response = client.get(inbox_url(session_id))

    assert response.status_code == 404
    assert "482913" not in response.text


def test_there_is_no_route_that_lists_every_inbox(client: TestClient) -> None:
    assert client.get("/v1/sessions").status_code == 405
