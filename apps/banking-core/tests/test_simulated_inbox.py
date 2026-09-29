"""Simulated OTP inbox on redis-core: TTL, session isolation, ACL-safe commands."""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import pytest
from banking_core.identity.config import (
    UnsupportedOtpChannelModeError,
    resolve_otp_channel_mode,
    simulated_inbox_enabled,
)
from banking_core.identity.ports import get_delivery_port
from banking_core.identity.simulated_inbox import (
    MAX_MESSAGES_PER_SESSION,
    SimulatedInbox,
    SimulatedInboxMessage,
    get_simulated_inbox,
    set_simulated_inbox,
)

START = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)

# The commands the documented core-svc ACL grants (docs/deployment.md). MULTI and
# EXEC are added by redis-py around a transaction and are granted too.
ACL_COMMANDS = {"GET", "SET", "DEL", "WATCH", "UNWATCH", "MULTI", "EXEC"}


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class RecordingRedis(fakeredis.FakeRedis):
    """FakeRedis that remembers every command name, pipelines included."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.commands: list[str] = []

    def execute_command(self, *args: Any, **options: Any) -> Any:
        self.commands.append(str(args[0]).upper())
        return super().execute_command(*args, **options)

    def pipeline(self, transaction: bool = True, shard_hint: Any = None) -> Any:
        pipe = super().pipeline(transaction, shard_hint)
        queue = pipe.execute_command

        def recording(*args: Any, **options: Any) -> Any:
            self.commands.append(str(args[0]).upper())
            return queue(*args, **options)

        pipe.execute_command = recording
        return pipe


@pytest.fixture
def redis_client() -> RecordingRedis:
    return RecordingRedis(decode_responses=True)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def inbox(redis_client: RecordingRedis, clock: Clock) -> SimulatedInbox:
    return SimulatedInbox(redis_client=redis_client, clock=clock)


def deliver(
    inbox: SimulatedInbox,
    session_id: str = "sess_a",
    challenge_id: str = "chal_a1",
    code: str = "482913",
    ttl_seconds: int = 300,
    channel: str = "EMAIL",
) -> None:
    inbox.deliver(
        session_id=session_id,
        challenge_id=challenge_id,
        channel=channel,
        destination_masked="d***@example.com",
        code=code,
        ttl_seconds=ttl_seconds,
    )


def test_delivered_code_is_listed_for_its_session(
    inbox: SimulatedInbox, clock: Clock
) -> None:
    deliver(inbox)

    [message] = inbox.messages("sess_a")

    assert message.model_dump(mode="json") == {
        "session_id": "sess_a",
        "challenge_id": "chal_a1",
        "channel": "EMAIL",
        "destination_masked": "d***@example.com",
        "code": "482913",
        "created_at": START.isoformat().replace("+00:00", "Z"),
        "expires_at": (START + timedelta(seconds=300))
        .isoformat()
        .replace("+00:00", "Z"),
    }


def test_entry_expires_with_the_challenge(
    inbox: SimulatedInbox, redis_client: RecordingRedis, clock: Clock
) -> None:
    deliver(inbox, ttl_seconds=120)

    # Redis drops the entry and the index with the challenge, not later.
    assert redis_client.ttl("otp:inbox:challenge:chal_a1") == 120
    assert redis_client.ttl("otp:inbox:session:sess_a") == 120

    clock.advance(119)
    assert [m.challenge_id for m in inbox.messages("sess_a")] == ["chal_a1"]
    assert inbox.get_code("chal_a1") == "482913"

    clock.advance(1)
    assert inbox.messages("sess_a") == []
    assert inbox.get_code("chal_a1") is None


def test_a_key_gone_from_redis_is_not_listed(
    inbox: SimulatedInbox, redis_client: RecordingRedis
) -> None:
    deliver(inbox, challenge_id="chal_a1")
    deliver(inbox, challenge_id="chal_a2", code="111111")

    redis_client.delete("otp:inbox:challenge:chal_a1")  # what the TTL does

    assert [m.challenge_id for m in inbox.messages("sess_a")] == ["chal_a2"]
    assert inbox.get_code("chal_a1") is None


def test_messages_come_newest_first_and_expired_ones_are_left_out(
    inbox: SimulatedInbox, clock: Clock
) -> None:
    deliver(inbox, challenge_id="chal_old", code="111111", ttl_seconds=30)
    clock.advance(10)
    deliver(inbox, challenge_id="chal_mid", code="222222", ttl_seconds=300)
    clock.advance(10)
    deliver(inbox, challenge_id="chal_new", code="333333", ttl_seconds=300)

    assert [m.challenge_id for m in inbox.messages("sess_a")] == [
        "chal_new",
        "chal_mid",
        "chal_old",
    ]

    clock.advance(15)  # chal_old (30 s) is gone, the others are not

    assert [m.challenge_id for m in inbox.messages("sess_a")] == [
        "chal_new",
        "chal_mid",
    ]


def test_a_session_only_sees_its_own_messages(inbox: SimulatedInbox) -> None:
    deliver(inbox, session_id="sess_a", challenge_id="chal_a1", code="111111")
    deliver(inbox, session_id="sess_b", challenge_id="chal_b1", code="222222")

    assert [m.code for m in inbox.messages("sess_a")] == ["111111"]
    assert [m.code for m in inbox.messages("sess_b")] == ["222222"]
    assert inbox.messages("sess_c") == []


def test_a_tampered_index_cannot_expose_another_sessions_entry(
    inbox: SimulatedInbox, redis_client: RecordingRedis, clock: Clock
) -> None:
    deliver(inbox, session_id="sess_b", challenge_id="chal_b1", code="222222")
    # Someone with write access to redis-core lists B's challenge under A.
    expires = (clock.now + timedelta(seconds=300)).timestamp()
    redis_client.set("otp:inbox:session:sess_a", json.dumps([["chal_b1", expires]]))

    assert inbox.messages("sess_a") == []
    assert [m.code for m in inbox.messages("sess_b")] == ["222222"]


def test_the_evaluation_hook_finds_a_code_by_challenge_alone(
    inbox: SimulatedInbox,
) -> None:
    deliver(inbox, session_id="sess_a", challenge_id="chal_a1", code="111111")
    deliver(inbox, session_id="sess_b", challenge_id="chal_b1", code="222222")

    assert inbox.get_code("chal_a1") == "111111"
    assert inbox.get_code("chal_b1") == "222222"
    assert inbox.get_code("chal_unknown") is None


def test_the_session_index_is_capped_and_dropped_entries_are_deleted(
    inbox: SimulatedInbox, redis_client: RecordingRedis, clock: Clock
) -> None:
    total = MAX_MESSAGES_PER_SESSION + 2
    for n in range(total):
        deliver(inbox, challenge_id=f"chal_{n:02d}", code=f"{n:06d}")
        clock.advance(1)

    kept = [m.challenge_id for m in inbox.messages("sess_a")]

    assert kept == [f"chal_{n:02d}" for n in reversed(range(2, total))]
    assert redis_client.get("otp:inbox:challenge:chal_00") is None
    assert redis_client.get("otp:inbox:challenge:chal_01") is None
    assert inbox.get_code("chal_00") is None
    assert len(json.loads(redis_client.get("otp:inbox:session:sess_a"))) == len(kept)


def test_redelivering_a_challenge_replaces_it(inbox: SimulatedInbox) -> None:
    deliver(inbox, code="111111")
    deliver(inbox, code="222222")

    [message] = inbox.messages("sess_a")
    assert message.code == "222222"


def test_only_commands_the_core_acl_grants_are_used(
    inbox: SimulatedInbox, redis_client: RecordingRedis
) -> None:
    deliver(inbox)
    deliver(inbox, challenge_id="chal_a2", code="111111")
    inbox.messages("sess_a")
    inbox.get_code("chal_a1")

    assert redis_client.commands
    assert set(redis_client.commands) <= ACL_COMMANDS
    keys = redis_client.keys("*")
    assert keys and all(key.startswith("otp:") for key in keys)


def test_the_key_prefix_comes_from_the_environment(
    redis_client: RecordingRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDIS_OTP_INBOX_KEY_PREFIX", "otp:box:")
    custom = SimulatedInbox(redis_client=redis_client)

    deliver(custom)

    assert sorted(redis_client.keys("*")) == [
        "otp:box:challenge:chal_a1",
        "otp:box:session:sess_a",
    ]
    assert custom.messages("sess_a")


def test_the_clear_code_lives_only_in_the_entry(
    inbox: SimulatedInbox,
    redis_client: RecordingRedis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    code = "482913"
    with caplog.at_level(logging.DEBUG):
        deliver(inbox, code=code)
        [message] = inbox.messages("sess_a")

    assert code not in caplog.text
    assert "sess_a" not in caplog.text
    assert "chal_a1" in caplog.text  # what is logged is the challenge, not the code
    assert code not in repr(message)
    assert code not in str(message)
    assert code not in redis_client.get("otp:inbox:session:sess_a")
    assert [k for k in redis_client.keys("*") if code in redis_client.get(k)] == [
        "otp:inbox:challenge:chal_a1"
    ]


def test_an_unreadable_entry_is_skipped_without_echoing_it(
    inbox: SimulatedInbox,
    redis_client: RecordingRedis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    deliver(inbox, challenge_id="chal_a1", code="482913")
    redis_client.set("otp:inbox:challenge:chal_a1", '{"code": "482913", "oops": 1')

    with caplog.at_level(logging.DEBUG):
        assert inbox.messages("sess_a") == []
        assert inbox.get_code("chal_a1") is None

    assert "482913" not in caplog.text


def test_a_ttl_below_one_second_is_refused(inbox: SimulatedInbox) -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        deliver(inbox, ttl_seconds=0)


def test_the_message_model_hides_the_code_in_its_repr() -> None:
    message = SimulatedInboxMessage(
        session_id="sess_a",
        challenge_id="chal_a1",
        channel="EMAIL",
        destination_masked="d***@example.com",
        code="482913",
        created_at=START,
        expires_at=START,
    )

    assert "482913" not in repr(message)


# --- OTP_CHANNEL_MODE ------------------------------------------------------


@pytest.mark.parametrize(
    "value", [None, "", "  ", "simulated", "SIMULATED", " Simulated "]
)
def test_simulated_is_the_only_mode_and_the_default(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("OTP_CHANNEL_MODE", raising=False)
    else:
        monkeypatch.setenv("OTP_CHANNEL_MODE", value)

    assert resolve_otp_channel_mode() == "simulated"
    assert simulated_inbox_enabled() is True


@pytest.mark.parametrize("value", ["smtp", "sms", "email", "real", "telegram"])
def test_any_other_mode_is_refused_with_an_explicit_message(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("OTP_CHANNEL_MODE", value)

    with pytest.raises(
        UnsupportedOtpChannelModeError,
        match="no real OTP delivery provider is implemented; "
        "set OTP_CHANNEL_MODE=simulated",
    ):
        resolve_otp_channel_mode()
    with pytest.raises(UnsupportedOtpChannelModeError):
        get_delivery_port()
    assert simulated_inbox_enabled() is False


def test_the_delivery_port_is_the_process_wide_simulated_inbox(
    monkeypatch: pytest.MonkeyPatch, redis_client: RecordingRedis
) -> None:
    monkeypatch.delenv("OTP_CHANNEL_MODE", raising=False)
    custom = SimulatedInbox(redis_client=redis_client)
    set_simulated_inbox(custom)
    try:
        assert get_delivery_port() is custom
        assert get_simulated_inbox() is custom
    finally:
        set_simulated_inbox(None)
