"""Redis URL and legacy connection configuration tests."""

from unittest.mock import Mock

import fakeredis
import pytest
from banking_core import redis_client
from banking_core.control.attempt_limits import AttemptLimitStore
from banking_core.control.session import RedisSessionStore
from banking_core.identity.challenge_store import OtpChallengeStore


def test_redis_url_precedes_legacy_connection_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "rediss://core-svc:placeholder@cache.example:6380/4"
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setenv("REDIS_HOST", "ignored.example")
    monkeypatch.setenv("REDIS_PORT", "16379")
    monkeypatch.setenv("REDIS_PASSWORD", "ignored")
    client = Mock()
    redis_factory = Mock()
    redis_factory.from_url.return_value = client
    monkeypatch.setattr(redis_client.redis, "Redis", redis_factory)

    actual = redis_client.create_redis_client()

    assert actual is client
    redis_factory.from_url.assert_called_once_with(url, decode_responses=True)
    redis_factory.assert_not_called()


def test_redis_legacy_connection_settings_remain_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_PORT", "16379")
    monkeypatch.setenv("REDIS_PASSWORD", "placeholder-password")
    monkeypatch.delenv("REDIS_URL", raising=False)
    client = Mock()
    redis_factory = Mock(return_value=client)
    monkeypatch.setattr(redis_client.redis, "Redis", redis_factory)

    actual = redis_client.create_redis_client()

    assert actual is client
    redis_factory.assert_called_once_with(
        host="redis.internal",
        port=16379,
        password="placeholder-password",
        decode_responses=True,
    )


def test_core_store_prefixes_are_configurable_and_keep_their_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDIS_SESSION_KEY_PREFIX", raising=False)
    monkeypatch.delenv("REDIS_OTP_CHALLENGE_KEY_PREFIX", raising=False)
    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    assert RedisSessionStore(redis_client=fake_redis)._key("s1") == "session:s1"
    assert OtpChallengeStore(redis_client=fake_redis)._key("c1") == "otp:challenge:c1"

    monkeypatch.setenv("REDIS_SESSION_KEY_PREFIX", "tenant:session:")
    monkeypatch.setenv("REDIS_OTP_CHALLENGE_KEY_PREFIX", "tenant:otp:")

    assert RedisSessionStore(redis_client=fake_redis)._key("s1") == "tenant:session:s1"
    challenge = OtpChallengeStore(redis_client=fake_redis)
    assert challenge._key("c1") == "tenant:otp:c1"
    assert challenge._evaluations_key("c1") == "tenant:otp:c1:evaluations"


def test_attempt_limit_prefix_is_configurable_and_keeps_its_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    customer = "6f1b3c1e-2a55-4e0a-9a51-0e6b1a3d9c11"
    monkeypatch.delenv("REDIS_ATTEMPT_LIMIT_KEY_PREFIX", raising=False)
    default = AttemptLimitStore(redis_client=fake_redis)
    assert default.key_prefix == "limit:"
    assert default._lock_key(customer) == f"limit:customer:{customer}:otp_lock"

    monkeypatch.setenv("REDIS_ATTEMPT_LIMIT_KEY_PREFIX", "tenant:limit:")
    tenant = AttemptLimitStore(redis_client=fake_redis)
    assert tenant._lock_key(customer) == f"tenant:limit:customer:{customer}:otp_lock"
    assert (
        tenant._document_key("a" * 64)
        == f"tenant:limit:document:{'a' * 64}:match_failures"
    )
