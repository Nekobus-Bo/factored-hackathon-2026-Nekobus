"""Storage and lifecycle verification for active OTP challenges on redis-core.

Security rules:
- The code is never stored in clear: only an HMAC-SHA256 keyed by a server key
  derived from MASTER_KEY, compared in constant time.
- Every evaluation increments an atomic counter (INCR) before the code is
  compared, so concurrent guesses can never exceed max_attempts evaluations.
- Redis is required: there is no in-process fallback, which would not be atomic
  across workers.
"""

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta

import redis
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from banking_core.crypto import get_master_key
from banking_core.redis_client import create_redis_client

OTP_HMAC_INFO = b"pattern-blue-otp-code-hmac-v1"


def derive_otp_hmac_key(master_key: str | bytes | None = None) -> bytes:
    """Derive the OTP HMAC key from MASTER_KEY, failing closed if it is missing."""
    resolved = get_master_key(master_key)
    raw = resolved.encode("utf-8") if isinstance(resolved, str) else resolved
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=OTP_HMAC_INFO)
    return hkdf.derive(raw)


class OtpChallengeStore:
    """Store for active OTP challenges with expiration and atomic attempt limiting."""

    def __init__(
        self,
        redis_client: redis.Redis,
        hmac_key: bytes | None = None,
        key_prefix: str | None = None,
    ) -> None:
        self._redis = redis_client
        self._hmac_key = hmac_key
        self.key_prefix = (
            key_prefix
            if key_prefix is not None
            else os.getenv("REDIS_OTP_CHALLENGE_KEY_PREFIX", "otp:challenge:")
        )

    def _key(self, challenge_id: str) -> str:
        return f"{self.key_prefix}{challenge_id}"

    def _evaluations_key(self, challenge_id: str) -> str:
        return f"{self.key_prefix}{challenge_id}:evaluations"

    def _digest(self, challenge_id: str, code: str) -> str:
        if self._hmac_key is None:
            self._hmac_key = derive_otp_hmac_key()
        message = f"{challenge_id}:{code}".encode()
        return hmac.new(self._hmac_key, message, hashlib.sha256).hexdigest()

    def create_challenge(
        self,
        challenge_id: str,
        customer_id: str,
        code: str,
        channel: str,
        destination_masked: str,
        ttl_seconds: int = 300,
        max_attempts: int = 3,
    ) -> None:
        """Create and store a fresh OTP challenge with TTL."""
        now = datetime.now(UTC)
        data = {
            "challenge_id": challenge_id,
            "customer_id": customer_id,
            "code_hmac": self._digest(challenge_id, code),
            "channel": channel,
            "destination_masked": destination_masked,
            "max_attempts": max_attempts,
            "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
            "created_at": now.isoformat(),
        }
        pipe = self._redis.pipeline()
        pipe.set(self._key(challenge_id), json.dumps(data), ex=ttl_seconds)
        pipe.delete(self._evaluations_key(challenge_id))
        pipe.execute()

    def verify_challenge(
        self,
        challenge_id: str,
        code: str,
    ) -> tuple[bool, int, str | None]:
        """Verify code against challenge.

        Returns:
            tuple[bool, int, str | None]: (is_valid, attempts_remaining, customer_id)
        """
        raw = self._redis.get(self._key(challenge_id))
        if raw is None:
            return False, 0, None
        data = json.loads(raw)
        customer_id: str | None = data.get("customer_id")
        max_attempts = int(data["max_attempts"])

        expires_at = datetime.fromisoformat(data["expires_at"])
        now = datetime.now(UTC)
        if now > expires_at:
            self.delete_challenge(challenge_id)
            return False, 0, customer_id

        # Reserve this evaluation atomically before comparing the code.
        pipe = self._redis.pipeline()
        pipe.incr(self._evaluations_key(challenge_id))
        pipe.expire(
            self._evaluations_key(challenge_id),
            max(1, int((expires_at - now).total_seconds())),
        )
        evaluation = int(pipe.execute()[0])
        if evaluation > max_attempts:
            self.delete_challenge(challenge_id)
            return False, 0, customer_id

        attempts_remaining = max_attempts - evaluation
        if hmac.compare_digest(data["code_hmac"], self._digest(challenge_id, code)):
            # Single use: only the caller that deletes the challenge succeeds.
            if self._redis.delete(self._key(challenge_id)) == 1:
                self._redis.delete(self._evaluations_key(challenge_id))
                return True, attempts_remaining + 1, customer_id
            return False, 0, customer_id

        if attempts_remaining <= 0:
            self.delete_challenge(challenge_id)
        return False, attempts_remaining, customer_id

    def evaluations(self, challenge_id: str) -> int:
        """Return how many codes were evaluated against the challenge."""
        raw = self._redis.get(self._evaluations_key(challenge_id))
        return int(raw) if raw is not None else 0

    def delete_challenge(self, challenge_id: str) -> None:
        """Remove challenge upon completion or lockout.

        The evaluation counter stays until its TTL so late guesses are still counted.
        """
        self._redis.delete(self._key(challenge_id))


_global_challenge_store: OtpChallengeStore | None = None


def get_challenge_store() -> OtpChallengeStore:
    """Get the singleton challenge store backed by redis-core."""
    global _global_challenge_store
    if _global_challenge_store is None:
        _global_challenge_store = OtpChallengeStore(redis_client=create_redis_client())
    return _global_challenge_store
