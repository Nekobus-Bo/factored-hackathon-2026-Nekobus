"""Database module for banking-core."""

from typing import Any

from banking_core.db.config import get_database_url
from banking_core.db.session import get_db, get_engine, get_session_maker

__all__ = [
    "SessionLocal",
    "engine",
    "get_database_url",
    "get_db",
    "get_engine",
    "get_session_maker",
]


def __getattr__(name: str) -> Any:
    """Lazy export of engine and SessionLocal."""
    import banking_core.db.session as session_mod

    if name in ("engine", "SessionLocal"):
        return getattr(session_mod, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
