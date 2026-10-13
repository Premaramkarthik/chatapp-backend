"""Redis connection settings tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config.settings import RedisSettings


def test_redis_url_uses_host_port_and_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_ENABLED", "true")
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_PASSWORD", "a-strong-password")
    monkeypatch.delenv("REDIS_URL", raising=False)

    settings = RedisSettings(_env_file=None)

    assert settings.url == "redis://:a-strong-password@redis:6380"


def test_redis_url_escapes_password_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_ENABLED", "true")
    monkeypatch.setenv("REDIS_HOST", "localhost")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_PASSWORD", "p@ss:/word")
    monkeypatch.delenv("REDIS_URL", raising=False)

    settings = RedisSettings(_env_file=None)

    assert settings.url == "redis://:p%40ss%3A%2Fword@localhost:6379"


def test_redis_url_override_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:16389/0")
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)

    settings = RedisSettings(_env_file=None)

    assert settings.url == "redis://localhost:16389/0"


def test_enabled_redis_requires_password_without_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_ENABLED", "true")
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ValidationError, match="REDIS_PASSWORD is required"):
        RedisSettings(_env_file=None)
