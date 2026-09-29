"""Per-client-IP limit on POST /v1/conversations (redis-edge, fixed window)."""

import ipaddress
from collections.abc import AsyncIterator, Callable
from typing import Any

import fakeredis
import httpx
import pytest
import respx
from fastapi import FastAPI
from orchestrator.chat.client_ip import UNKNOWN_CLIENT, resolve_client_ip
from orchestrator.config import Settings
from orchestrator.session.rate_limit import ConversationRateLimiter
from redis.exceptions import ConnectionError as RedisConnectionError

from .fake_handler import FakeTurnHandler
from .test_chat_api import BANKING_URL, build_app

LIMIT = 3
CLIENT_A = "203.0.113.7"
CLIENT_B = "198.51.100.23"
PROXY = "10.0.0.5"


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis()


@pytest.fixture
def banking_sessions() -> Any:
    """The banking-core session route; its call count says whether one was opened."""
    with respx.mock(assert_all_called=False) as router:
        yield router.post(f"{BANKING_URL}/v1/sessions").mock(
            return_value=httpx.Response(201, json={"session_id": "sess_opaque_0001"})
        )


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR", str(LIMIT))
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    return Settings(_env_file=None)


@pytest.fixture
async def make_client() -> AsyncIterator[Callable[[FastAPI, str], httpx.AsyncClient]]:
    clients: list[httpx.AsyncClient] = []

    def _make(app: FastAPI, peer: str = CLIENT_A) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(peer, 50000)),
            base_url="http://orch",
        )
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()


async def open_conversations(
    client: httpx.AsyncClient, count: int, **headers: str
) -> list[httpx.Response]:
    return [
        await client.post("/v1/conversations", headers=headers) for _ in range(count)
    ]


async def test_over_the_limit_is_429_with_retry_after_and_opens_no_banking_session(
    redis: fakeredis.FakeAsyncRedis,
    banking_sessions: Any,
    settings: Settings,
    make_client: Any,
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=settings))

    allowed = await open_conversations(client, LIMIT)
    assert [r.status_code for r in allowed] == [201] * LIMIT
    assert banking_sessions.call_count == LIMIT
    conversations_before = await redis.keys("orch:conv:*")

    refused = await client.post("/v1/conversations", json={"lang": "en"})

    assert refused.status_code == 429
    retry_after = int(refused.headers["Retry-After"])
    assert 1 <= retry_after <= 3600
    assert refused.json() == {
        "detail": "Too many conversations opened from this address; try again later"
    }
    # Nothing was opened: no banking session, no conversation state.
    assert banking_sessions.call_count == LIMIT
    assert await redis.keys("orch:conv:*") == conversations_before
    # And it stays refused until the window ends.
    again = await client.post("/v1/conversations")
    assert again.status_code == 429


async def test_each_address_has_its_own_budget(
    redis: fakeredis.FakeAsyncRedis,
    banking_sessions: Any,
    settings: Settings,
    make_client: Any,
) -> None:
    app = build_app(redis, FakeTurnHandler(), settings=settings)
    first = make_client(app, CLIENT_A)
    second = make_client(app, CLIENT_B)
    await open_conversations(first, LIMIT + 2)

    fresh = await open_conversations(second, LIMIT)

    assert [r.status_code for r in fresh] == [201] * LIMIT
    assert (await second.post("/v1/conversations")).status_code == 429
    assert (await first.post("/v1/conversations")).status_code == 429


async def test_only_conversation_creation_is_limited(
    redis: fakeredis.FakeAsyncRedis,
    banking_sessions: Any,
    settings: Settings,
    make_client: Any,
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=settings))
    created = await client.post("/v1/conversations")
    conversation_id = created.json()["conversation_id"]
    await open_conversations(client, LIMIT)
    assert (await client.post("/v1/conversations")).status_code == 429

    transcript = await client.get(f"/v1/conversations/{conversation_id}")
    message = await client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"text": "hola"}
    )

    assert transcript.status_code == 200
    assert message.status_code == 200


async def test_forwarded_header_is_ignored_by_default(
    redis: fakeredis.FakeAsyncRedis,
    banking_sessions: Any,
    settings: Settings,
    make_client: Any,
) -> None:
    client = make_client(build_app(redis, FakeTurnHandler(), settings=settings))

    # A new "client" in every request does not buy a new budget.
    statuses = [
        (
            await client.post(
                "/v1/conversations",
                headers={"X-Forwarded-For": f"192.0.2.{i}, 192.0.2.{i + 100}"},
            )
        ).status_code
        for i in range(LIMIT + 3)
    ]

    assert statuses == [201] * LIMIT + [429] * 3
    assert banking_sessions.call_count == LIMIT


async def test_forwarded_header_is_honored_with_a_trusted_hop(
    redis: fakeredis.FakeAsyncRedis,
    banking_sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    make_client: Any,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    hopped = Settings(_env_file=None)
    client = make_client(build_app(redis, FakeTurnHandler(), settings=hopped), PROXY)

    # The proxy appends the address it saw. Whatever the client put before it is
    # its own claim and never selects the bucket.
    a = await open_conversations(client, LIMIT, **{"X-Forwarded-For": CLIENT_A})
    spoofed = await open_conversations(
        client, 2, **{"X-Forwarded-For": f"9.9.9.9, {CLIENT_A}"}
    )
    b = await open_conversations(client, LIMIT, **{"X-Forwarded-For": CLIENT_B})

    assert [r.status_code for r in a] == [201] * LIMIT
    assert [r.status_code for r in spoofed] == [429] * 2
    assert [r.status_code for r in b] == [201] * LIMIT


async def test_without_a_forwarded_header_a_trusted_hop_limits_the_peer(
    redis: fakeredis.FakeAsyncRedis,
    banking_sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
    make_client: Any,
    settings: Settings,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    hopped = Settings(_env_file=None)
    client = make_client(build_app(redis, FakeTurnHandler(), settings=hopped), PROXY)

    statuses = [r.status_code for r in await open_conversations(client, LIMIT + 1)]

    assert statuses == [201] * LIMIT + [429]


async def test_no_raw_address_reaches_redis(
    redis: fakeredis.FakeAsyncRedis,
    banking_sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    make_client: Any,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    hopped = Settings(_env_file=None)
    client = make_client(build_app(redis, FakeTurnHandler(), settings=hopped), PROXY)
    await open_conversations(client, LIMIT + 1, **{"X-Forwarded-For": CLIENT_A})

    keys = [k.decode() for k in await redis.keys("*") if b"ratelimit" in k]

    assert len(keys) == 1
    assert keys[0].startswith("orch:ratelimit:conversations:")
    _, _, _, digest, window = keys[0].split(":")
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert window.isdigit()
    for raw in (CLIENT_A, PROXY):
        assert raw not in keys[0]
        for key in await redis.keys("*"):
            assert raw.encode() not in key
            value = await redis.get(key)
            assert value is None or raw.encode() not in value


async def test_a_redis_outage_fails_closed_without_opening_a_banking_session(
    redis: fakeredis.FakeAsyncRedis,
    banking_sessions: Any,
    settings: Settings,
    make_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_app(redis, FakeTurnHandler(), settings=settings)
    client = make_client(app)

    async def unreachable(self: Any, client_ip: str) -> Any:
        raise RedisConnectionError("edge redis is down")

    monkeypatch.setattr(ConversationRateLimiter, "hit", unreachable)

    refused = await client.post("/v1/conversations")

    assert refused.status_code == 503
    assert "Retry-After" not in refused.headers
    assert banking_sessions.call_count == 0


async def test_the_key_prefix_is_configurable(
    redis: fakeredis.FakeAsyncRedis,
    banking_sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    make_client: Any,
) -> None:
    monkeypatch.setenv("REDIS_EDGE_RATE_LIMIT_KEY_PREFIX", "tenant:orch:rl:")
    tenant = Settings(_env_file=None)
    client = make_client(build_app(redis, FakeTurnHandler(), settings=tenant))
    await client.post("/v1/conversations")

    assert [k.decode() for k in await redis.keys("tenant:orch:rl:*")] != []
    assert await redis.keys("orch:ratelimit:*") == []


def test_settings_seed_the_limit_and_ignore_the_header_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR",
        "TRUSTED_PROXY_HOPS",
        "REDIS_EDGE_RATE_LIMIT_KEY_PREFIX",
    ):
        monkeypatch.delenv(name, raising=False)

    seeded = Settings(_env_file=None)

    assert seeded.rate_limit_conversations_per_ip_hour == 30
    assert seeded.trusted_proxy_hops == 0
    assert seeded.redis_edge_rate_limit_key_prefix == "orch:ratelimit:"


@pytest.mark.parametrize(
    "name, value",
    [
        ("RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR", "0"),
        ("TRUSTED_PROXY_HOPS", "-1"),
        ("TRUSTED_PROXY_HOPS", "9"),
    ],
)
def test_settings_refuse_values_that_would_disable_or_misplace_the_limit(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


async def test_the_window_is_fixed_and_retry_after_counts_down_to_its_end(
    redis: fakeredis.FakeAsyncRedis,
) -> None:
    clock = FakeClock(now=7200.0 + 100.0)  # 100 s into a window
    limiter = ConversationRateLimiter(
        redis, secret="s3cret", limit=2, key_prefix="orch:ratelimit:", clock=clock
    )

    first = await limiter.hit(CLIENT_A)
    second = await limiter.hit(CLIENT_A)
    third = await limiter.hit(CLIENT_A)

    assert (first.allowed, second.allowed, third.allowed) == (True, True, False)
    assert third.retry_after_seconds == 3500

    clock.now = 7200.0 + 3599.2
    assert (await limiter.hit(CLIENT_A)).retry_after_seconds == 1

    # The next window starts from zero.
    clock.now = 10800.0
    assert (await limiter.hit(CLIENT_A)).allowed is True


async def test_every_key_expires_with_its_window(
    redis: fakeredis.FakeAsyncRedis,
) -> None:
    limiter = ConversationRateLimiter(
        redis, secret="s3cret", limit=2, window_seconds=600, clock=FakeClock(1000.0)
    )
    await limiter.hit(CLIENT_A)

    (key,) = await redis.keys("orch:ratelimit:*")

    assert 0 < await redis.ttl(key) <= 600


async def test_the_key_depends_on_the_secret_and_not_on_the_address_text(
    redis: fakeredis.FakeAsyncRedis,
) -> None:
    one = ConversationRateLimiter(redis, secret="one", limit=1)
    other = ConversationRateLimiter(redis, secret="other", limit=1)

    assert one._key(CLIENT_A, 5) != other._key(CLIENT_A, 5)
    assert one._key(CLIENT_A, 5) != one._key(CLIENT_B, 5)
    assert one._key(CLIENT_A, 5) != one._key(CLIENT_A, 6)


@pytest.mark.parametrize(
    "peer, headers, hops, expected",
    [
        # Default: the header never counts.
        (CLIENT_A, ["1.1.1.1"], 0, CLIENT_A),
        (CLIENT_A, [], 0, CLIENT_A),
        # One trusted proxy: the client is the last entry, the peer is the proxy.
        (PROXY, [CLIENT_A], 1, CLIENT_A),
        (PROXY, [f"9.9.9.9, {CLIENT_A}"], 1, CLIENT_A),
        # Several header lines are one list.
        (PROXY, ["9.9.9.9", CLIENT_A], 1, CLIENT_A),
        # Two trusted proxies: the client is second from the right.
        (PROXY, [f"{CLIENT_A}, 172.16.0.9"], 2, CLIENT_A),
        (PROXY, [f"7.7.7.7, {CLIENT_A}, 172.16.0.9"], 2, CLIENT_A),
        # Header shorter than the trusted chain: fall back to the peer.
        (PROXY, [], 1, PROXY),
        (PROXY, [CLIENT_A], 2, PROXY),
        # The chosen entry is not an address: fall back to the peer.
        (PROXY, ["unknown"], 1, PROXY),
        (PROXY, [f"{CLIENT_A}:8080"], 1, PROXY),
        # No peer at all.
        (None, [CLIENT_A], 1, UNKNOWN_CLIENT),
        (None, [], 0, UNKNOWN_CLIENT),
    ],
)
def test_client_address_resolution(
    peer: str | None, headers: list[str], hops: int, expected: str
) -> None:
    assert resolve_client_ip(peer, headers, hops) == expected


def test_ipv6_clients_are_grouped_by_their_64_bit_prefix() -> None:
    inside = ["2001:db8:1:2::1", "2001:db8:1:2:aaaa:bbbb:cccc:dddd"]
    outside = "2001:db8:1:3::1"

    grouped = {resolve_client_ip(a, [], 0) for a in inside}

    assert len(grouped) == 1
    assert ipaddress.ip_address(inside[0]) in ipaddress.ip_network(grouped.pop())
    assert resolve_client_ip(outside, [], 0) != resolve_client_ip(inside[0], [], 0)


def test_an_ipv4_mapped_ipv6_peer_is_the_ipv4_address() -> None:
    assert resolve_client_ip("::ffff:203.0.113.7", [], 0) == "203.0.113.7"
