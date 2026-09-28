"""Redis connection and key-prefix configuration tests."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from orchestrator.config import Settings
from orchestrator.main import create_app

from .fake_handler import FakeTurnHandler


def test_redis_edge_url_precedes_generic_url_and_is_secret_safe(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    edge_url = "rediss://edge-svc:placeholder@cache.example:6381/3"
    monkeypatch.setenv("REDIS_EDGE_URL", edge_url)
    monkeypatch.setenv("REDIS_URL", "redis://generic:placeholder@other.example/0")
    monkeypatch.setenv("REDIS_EDGE_KEY_PREFIX", "tenant:orch:")
    monkeypatch.setenv("SESSION_SECRET", "placeholder-session-secret")
    settings = Settings(_env_file=None)

    assert settings.redis_edge_url is not None
    assert settings.redis_edge_url.get_secret_value() == edge_url
    assert edge_url not in repr(settings)
    assert edge_url not in str(settings)
    with caplog.at_level(logging.INFO):
        logging.getLogger(__name__).info("settings: %r", settings)
    assert edge_url not in caplog.text

    redis_client = MagicMock()
    with patch("orchestrator.main.Redis") as redis_factory:
        redis_factory.from_url.return_value = redis_client
        app = create_app(
            settings=settings,
            banking_client=MagicMock(),
            turn_handler=FakeTurnHandler(),
        )

    redis_factory.from_url.assert_called_once_with(edge_url)
    assert app.state.session_store.redis is redis_client
    assert app.state.session_store.key_prefix == "tenant:orch:"


def test_generic_redis_url_alias_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "redis://edge-svc:placeholder@cache.example:6379/2"
    monkeypatch.delenv("REDIS_EDGE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", url)

    settings = Settings(_env_file=None)

    assert settings.redis_edge_url is not None
    assert settings.redis_edge_url.get_secret_value() == url


def test_orchestrator_falls_back_to_legacy_redis_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDIS_EDGE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_EDGE_KEY_PREFIX", raising=False)
    monkeypatch.setenv("REDIS_EDGE_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_EDGE_PORT", "16379")
    monkeypatch.setenv("REDIS_EDGE_PASSWORD", "placeholder-password")
    monkeypatch.setenv("SESSION_SECRET", "placeholder-session-secret")
    settings = Settings(_env_file=None)
    redis_client = MagicMock()

    with patch("orchestrator.main.Redis") as redis_factory:
        redis_factory.return_value = redis_client
        app = create_app(
            settings=settings,
            banking_client=MagicMock(),
            turn_handler=FakeTurnHandler(),
        )

    redis_factory.assert_called_once_with(
        host="redis.internal", port=16379, password="placeholder-password"
    )
    assert app.state.session_store.redis is redis_client
    assert app.state.session_store.key_prefix == "orch:conv:"
