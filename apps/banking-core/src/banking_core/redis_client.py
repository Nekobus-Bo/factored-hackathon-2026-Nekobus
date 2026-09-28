"""Redis client configuration shared by banking-core stores."""

import os

import redis


def create_redis_client() -> redis.Redis:
    """Build a Redis client from REDIS_URL or the legacy connection settings."""
    if url := os.getenv("REDIS_URL"):
        return redis.Redis.from_url(url, decode_responses=True)

    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
    )
