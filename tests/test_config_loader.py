"""Tests for config.yaml loading and env override behavior."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.config.loader import (
    apply_yaml_defaults_to_env,
    load_yaml_config,
    validate_production_settings,
)
from v1.utils.base import ConfigurationError


def test_load_yaml_config_maps_nested_keys(tmp_path: Path) -> None:
    """YAML nested keys flatten to environment variable names."""
    config = tmp_path / "config.yaml"
    config.write_text(
        """
app:
  name: Test App
  environment: staging
jwt:
  audience: test-api
  jwks_cache_ttl: 600
""",
        encoding="utf-8",
    )
    flat = load_yaml_config(config)
    assert flat["APP_NAME"] == "Test App"
    assert flat["APP_ENV"] == "staging"
    assert flat["KEYCLOAK_AUDIENCE"] == "test-api"
    assert flat["KEYCLOAK_JWKS_CACHE_TTL_SEC"] == 600


def test_repository_yaml_loads_operational_defaults() -> None:
    flat = load_yaml_config(Path(__file__).resolve().parents[1] / "config.yaml")
    assert "http://localhost:8080" in flat["MIDDLEWARE_CORS_ORIGINS"]
    assert flat["DB_POOL_AUTO_CONCURRENT_REQUESTS"] == 16
    assert flat["AUTH_COOKIE_SECURE"] is False
    assert flat["AUTH_VERIFICATION_RECONCILE_ENABLED"] is False
    assert flat["MATRIX_IMAGE_MAX_BYTES"] == 10485760
    assert flat["TYPESENSE_USERS_COLLECTION"] == "users"
    assert flat["SEARCH_CACHE_TTL_CITY_SEC"] == 86400
    assert not any("SECRET" in key or key.endswith("PASSWORD") for key in flat)


def test_apply_yaml_defaults_does_not_override_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Environment variables take precedence over YAML defaults."""
    config = tmp_path / "config.yaml"
    config.write_text("app:\n  name: From Yaml\n", encoding="utf-8")
    monkeypatch.setenv("APP_NAME", "From Env")
    apply_yaml_defaults_to_env(config)
    assert os.environ["APP_NAME"] == "From Env"


def test_validate_production_settings_rejects_debug() -> None:
    """Production environment rejects debug mode."""
    with pytest.raises(ConfigurationError):
        validate_production_settings(environment="production", debug=True)


def test_local_env_overrides_yaml_but_preserves_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("app:\n  name: From Yaml\n  debug: true\n", encoding="utf-8")
    (tmp_path / ".env").write_text("APP_NAME=From Dotenv\nAPP_DEBUG=false\n", encoding="utf-8")
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.setenv("APP_DEBUG", "true")
    apply_yaml_defaults_to_env(config)
    assert os.environ["APP_NAME"] == "From Dotenv"
    assert os.environ["APP_DEBUG"] == "true"


def test_validate_production_settings_rejects_auto_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production environment rejects Keycloak auto-bootstrap."""
    monkeypatch.setenv("KEYCLOAK_AUTO_BOOTSTRAP", "true")
    with pytest.raises(ConfigurationError, match="KEYCLOAK_AUTO_BOOTSTRAP"):
        validate_production_settings(environment="production", debug=False)
