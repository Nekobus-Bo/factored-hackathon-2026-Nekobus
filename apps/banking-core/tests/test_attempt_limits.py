"""Cross-session attempt limit store: counters, windows, locks and keys (redis-core)."""

import re
import threading
import uuid

import fakeredis
import pytest
from banking_core.control.attempt_limits import (
    AttemptLimits,
    AttemptLimitStore,
    DocumentAttempt,
    document_ref,
)
from banking_core.control.policy import PolicyConfig

CUSTOMER = "6f1b3c1e-2a55-4e0a-9a51-0e6b1a3d9c11"
OTHER_CUSTOMER = "0d3f2a7c-88b1-4d55-8a4e-5b2c7d1e9f22"
BIDX = "a" * 64
OTHER_BIDX = "b" * 64
THIRD_BIDX = "c" * 64
MAX = 3
WINDOW = 600
LOCK = 900


@pytest.fixture
def redis_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def store(redis_client: fakeredis.FakeRedis) -> AttemptLimitStore:
    return AttemptLimitStore(redis_client=redis_client)


def fail_verify(store: AttemptLimitStore, customer: str = CUSTOMER) -> bool:
    return store.record_failed_verify(
        customer, max_failures=MAX, window_seconds=WINDOW, lock_seconds=LOCK
    )


def reserve(store: AttemptLimitStore, *blind_indexes: str) -> DocumentAttempt:
    return store.reserve_document_attempt(
        blind_indexes, max_failures=MAX, window_seconds=WINDOW
    )


def test_customer_is_locked_exactly_when_the_failure_maximum_is_reached(
    store: AttemptLimitStore,
) -> None:
    assert not store.customer_locked(CUSTOMER)
    outcomes = [fail_verify(store) for _ in range(MAX)]

    assert outcomes == [False] * (MAX - 1) + [True]
    assert store.customer_locked(CUSTOMER)
    assert not store.customer_locked(OTHER_CUSTOMER)


def test_only_the_failure_that_creates_the_lock_reports_it(
    store: AttemptLimitStore,
) -> None:
    for _ in range(MAX):
        fail_verify(store)

    # Late failures (a race with the lock) never re-announce it.
    assert [fail_verify(store) for _ in range(3)] == [False, False, False]
    assert store.customer_locked(CUSTOMER)


def test_customers_are_counted_apart(store: AttemptLimitStore) -> None:
    for _ in range(MAX - 1):
        fail_verify(store)
        fail_verify(store, OTHER_CUSTOMER)

    assert fail_verify(store) is True
    assert not store.customer_locked(OTHER_CUSTOMER)


def test_the_window_opens_with_the_first_failure_and_is_not_extended(
    store: AttemptLimitStore, redis_client: fakeredis.FakeRedis
) -> None:
    key = f"limit:customer:{CUSTOMER}:otp_failures"
    fail_verify(store)
    redis_client.expire(key, 100)

    fail_verify(store)

    assert 0 < redis_client.ttl(key) <= 100


def test_counter_and_lock_expire_with_their_configured_durations(
    store: AttemptLimitStore, redis_client: fakeredis.FakeRedis
) -> None:
    for _ in range(MAX):
        fail_verify(store)

    assert 0 < redis_client.ttl(f"limit:customer:{CUSTOMER}:otp_failures") <= WINDOW
    assert 0 < redis_client.ttl(f"limit:customer:{CUSTOMER}:otp_lock") <= LOCK

    # Once the lock is gone the customer can try again.
    redis_client.delete(f"limit:customer:{CUSTOMER}:otp_lock")
    assert not store.customer_locked(CUSTOMER)


def test_a_failure_after_the_lock_ends_inside_the_same_window_locks_again(
    store: AttemptLimitStore, redis_client: fakeredis.FakeRedis
) -> None:
    for _ in range(MAX):
        fail_verify(store)
    redis_client.delete(f"limit:customer:{CUSTOMER}:otp_lock")

    assert fail_verify(store) is True


def test_document_attempts_are_blocked_past_the_maximum(
    store: AttemptLimitStore,
) -> None:
    attempts = [reserve(store, BIDX) for _ in range(MAX + 3)]

    assert [a.blocked for a in attempts] == [False] * MAX + [True] * 3


def test_the_first_blocked_attempt_reports_the_document_once(
    store: AttemptLimitStore,
) -> None:
    attempts = [reserve(store, BIDX) for _ in range(MAX + 3)]

    assert [a.limit_reached_ref for a in attempts] == (
        [None] * MAX + [document_ref(BIDX)] + [None] * 2
    )


def test_documents_are_counted_apart(store: AttemptLimitStore) -> None:
    for _ in range(MAX + 1):
        reserve(store, BIDX)

    assert reserve(store, BIDX).blocked
    assert not reserve(store, OTHER_BIDX).blocked


def test_a_successful_match_gives_its_attempt_back(store: AttemptLimitStore) -> None:
    for _ in range(MAX - 1):
        reserve(store, BIDX)
    success = reserve(store, BIDX)
    assert not success.blocked
    store.release_document_attempt(success)

    # Only the failures stay counted: MAX - 1 of them, so one more fits.
    assert not reserve(store, BIDX).blocked
    assert reserve(store, BIDX).blocked


def test_giving_back_never_creates_a_key_or_touches_the_ttl(
    store: AttemptLimitStore, redis_client: fakeredis.FakeRedis
) -> None:
    attempt = reserve(store, BIDX)
    (key,) = attempt.counters
    redis_client.expire(key, 100)
    store.release_document_attempt(attempt)
    assert redis_client.get(key) == "0"
    assert 0 < redis_client.ttl(key) <= 100

    # The window ended while the match was running: nothing comes back to life.
    redis_client.delete(key)
    store.release_document_attempt(attempt)
    assert redis_client.exists(key) == 0


def test_equivalent_document_types_share_the_limit(store: AttemptLimitStore) -> None:
    # A claim as TAX_ID probes [TAX_ID, NATIONAL_ID]; a claim as NATIONAL_ID probes
    # the same two indexes in the other order: same counters, same limit.
    for _ in range(MAX):
        reserve(store, BIDX, OTHER_BIDX)

    assert reserve(store, OTHER_BIDX, BIDX).blocked
    assert reserve(store, BIDX).blocked
    assert reserve(store, OTHER_BIDX).blocked
    assert not reserve(store, THIRD_BIDX).blocked


def test_a_repeated_blind_index_counts_once_per_attempt(
    store: AttemptLimitStore, redis_client: fakeredis.FakeRedis
) -> None:
    attempt = reserve(store, BIDX, BIDX)

    assert len(attempt.counters) == 1
    assert redis_client.get(attempt.counters[0]) == "1"


def test_no_blind_index_means_nothing_to_count(store: AttemptLimitStore) -> None:
    attempt = reserve(store)

    assert attempt.counters == ()
    assert attempt.blocked is False
    store.release_document_attempt(attempt)


def test_parallel_attempts_never_evaluate_past_the_maximum(
    store: AttemptLimitStore,
) -> None:
    results = []
    barrier = threading.Barrier(40)

    def attempt() -> None:
        barrier.wait()
        results.append(reserve(store, BIDX))

    threads = [threading.Thread(target=attempt) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(1 for r in results if not r.blocked) == MAX
    assert sum(1 for r in results if r.limit_reached_ref) == 1


def test_parallel_failed_verifies_lock_the_customer_exactly_once(
    store: AttemptLimitStore,
) -> None:
    outcomes = []
    barrier = threading.Barrier(30)

    def fail() -> None:
        barrier.wait()
        outcomes.append(fail_verify(store))

    threads = [threading.Thread(target=fail) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count(True) == 1
    assert store.customer_locked(CUSTOMER)


def test_keys_hold_only_a_uuid_or_a_blind_index_under_the_prefix(
    store: AttemptLimitStore, redis_client: fakeredis.FakeRedis
) -> None:
    for _ in range(MAX):
        fail_verify(store)
    reserve(store, BIDX)

    keys = sorted(redis_client.keys("*"))
    assert keys == [
        f"limit:customer:{CUSTOMER}:otp_failures",
        f"limit:customer:{CUSTOMER}:otp_lock",
        f"limit:document:{BIDX}:match_failures",
    ]
    for key in keys:
        assert re.fullmatch(
            r"limit:(customer:[0-9a-f-]{36}:otp_(failures|lock)"
            r"|document:[0-9a-f]{64}:match_failures)",
            key,
        )


@pytest.mark.parametrize(
    "not_an_id", ["1020304050", "Carlos Gomez", "carlos@example.com", "", "12345"]
)
def test_a_customer_key_refuses_anything_but_a_uuid(
    store: AttemptLimitStore, not_an_id: str
) -> None:
    with pytest.raises(ValueError):
        fail_verify(store, not_an_id)
    with pytest.raises(ValueError):
        store.customer_locked(not_an_id)


@pytest.mark.parametrize(
    "not_an_index", ["1020304050", "carlos@example.com", "A" * 64, "a" * 63, ""]
)
def test_a_document_key_refuses_anything_but_a_blind_index(
    store: AttemptLimitStore, not_an_index: str
) -> None:
    with pytest.raises(ValueError):
        reserve(store, not_an_index)


def test_audit_reference_is_a_hash_sized_prefix_of_the_blind_index() -> None:
    ref = document_ref(uuid.uuid4().hex + uuid.uuid4().hex)

    assert len(ref) == 32
    assert re.fullmatch(r"[0-9a-f]{32}", ref)


def test_limits_take_their_thresholds_from_the_policy_config(
    redis_client: fakeredis.FakeRedis,
) -> None:
    config = PolicyConfig(
        customer_otp_max_failures=2,
        customer_otp_window_seconds=120,
        customer_otp_lock_seconds=240,
        document_match_max_failures=1,
        document_match_window_seconds=180,
    )
    limits = AttemptLimits.from_config(
        AttemptLimitStore(redis_client=redis_client), config
    )

    assert limits.record_failed_verify(CUSTOMER) is False
    assert limits.record_failed_verify(CUSTOMER) is True
    assert limits.customer_locked(CUSTOMER)
    assert 0 < redis_client.ttl(f"limit:customer:{CUSTOMER}:otp_failures") <= 120
    assert 0 < redis_client.ttl(f"limit:customer:{CUSTOMER}:otp_lock") <= 240

    assert limits.reserve_document_attempt([BIDX]).blocked is False
    assert limits.reserve_document_attempt([BIDX]).blocked is True
    assert 0 < redis_client.ttl(f"limit:document:{BIDX}:match_failures") <= 180
