"""Database session and engine management."""

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from banking_core.db.config import get_database_url

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Get or create singleton database engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_url(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_maker() -> sessionmaker[Session]:
    """Get or create singleton session maker."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def __getattr__(name: str) -> Any:
    """Lazy module attribute access for engine and SessionLocal."""
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_session_maker()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def get_db() -> Generator[Session, None, None]:
    """Dependency for obtaining a database session."""
    session = get_session_maker()()
    try:
        yield session
    finally:
        session.close()
