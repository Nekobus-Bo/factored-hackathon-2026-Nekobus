"""Database connection configuration."""

import os


def get_database_url() -> str:
    """Build PostgreSQL connection URL using psycopg 3 driver.

    Raises:
        ValueError: If POSTGRES_PASSWORD is missing and DATABASE_URL is not provided.
    """
    if url := os.getenv("DATABASE_URL"):
        return url
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise ValueError(
            "POSTGRES_PASSWORD environment variable is required and cannot be empty"
        )
    user = os.getenv("POSTGRES_USER", "app")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "bank")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"
