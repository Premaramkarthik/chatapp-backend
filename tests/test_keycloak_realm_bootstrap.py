"""Tests for Keycloak realm auto-bootstrap."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from infrastructure.keycloak.realm_bootstrap import ensure_keycloak_realm
from v1.utils.base import ConfigurationError


def _mock_settings(**overrides: object) -> MagicMock:
    settings = MagicMock()
    settings.keycloak.enabled = overrides.get("enabled", True)
    settings.keycloak.auto_bootstrap = overrides.get("auto_bootstrap", True)
    settings.keycloak.realm = "chatapp"
    settings.keycloak.internal_base = "http://localhost:8180"
    settings.keycloak.well_known_url = (
        "http://localhost:8180/realms/chatapp/.well-known/openid-configuration"
    )
    settings.keycloak.bootstrap_admin = overrides.get("bootstrap_admin", "admin")
    settings.keycloak.bootstrap_admin_password_value = overrides.get(
        "bootstrap_admin_password",
        "admin",
    )
    settings.http.timeout_seconds = 5.0
    return settings


@pytest.mark.asyncio
async def test_ensure_keycloak_realm_skips_when_disabled() -> None:
    """Bootstrap is a no-op when Keycloak integration is disabled."""
    with patch("infrastructure.keycloak.realm_bootstrap.settings", _mock_settings(enabled=False)):
        with patch(
            "infrastructure.keycloak.realm_bootstrap.wait_for_keycloak",
            new_callable=AsyncMock,
        ) as mock_wait:
            await ensure_keycloak_realm()
    mock_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_keycloak_realm_skips_when_auto_bootstrap_false() -> None:
    """Bootstrap is a no-op when auto_bootstrap is disabled."""
    with patch(
        "infrastructure.keycloak.realm_bootstrap.settings",
        _mock_settings(auto_bootstrap=False),
    ):
        with patch(
            "infrastructure.keycloak.realm_bootstrap.wait_for_keycloak",
            new_callable=AsyncMock,
        ) as mock_wait:
            await ensure_keycloak_realm()
    mock_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_keycloak_realm_skips_when_well_known_exists() -> None:
    """Existing realm discovery document skips bootstrap."""
    discovery_response = MagicMock()
    discovery_response.status_code = 200

    with patch("infrastructure.keycloak.realm_bootstrap.settings", _mock_settings()):
        with patch(
            "infrastructure.keycloak.realm_bootstrap.wait_for_keycloak",
            new_callable=AsyncMock,
        ):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get = AsyncMock(return_value=discovery_response)
                mock_client_cls.return_value = mock_client

                with patch(
                    "infrastructure.keycloak.realm_bootstrap.get_master_admin_token",
                    new_callable=AsyncMock,
                ) as mock_token:
                    await ensure_keycloak_realm()

    mock_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_keycloak_realm_creates_on_404() -> None:
    """Missing realm triggers POST /admin/realms with the template payload."""
    discovery_response = MagicMock()
    discovery_response.status_code = 404
    create_response = MagicMock()
    create_response.status_code = 201
    realm_payload = {"realm": "chatapp"}

    with patch("infrastructure.keycloak.realm_bootstrap.settings", _mock_settings()):
        with patch(
            "infrastructure.keycloak.realm_bootstrap.wait_for_keycloak",
            new_callable=AsyncMock,
        ):
            with patch(
                "infrastructure.keycloak.realm_bootstrap._load_realm_template",
                return_value=realm_payload,
            ):
                with patch(
                    "infrastructure.keycloak.realm_bootstrap.get_master_admin_token",
                    new_callable=AsyncMock,
                    return_value="master-token",
                ):
                    with patch("httpx.AsyncClient") as mock_client_cls:
                        mock_client = AsyncMock()
                        mock_client.__aenter__.return_value = mock_client
                        mock_client.__aexit__.return_value = None
                        mock_client.get = AsyncMock(return_value=discovery_response)
                        mock_client.post = AsyncMock(return_value=create_response)
                        mock_client_cls.return_value = mock_client

                        await ensure_keycloak_realm()

    mock_client.post.assert_awaited_once()
    post_kwargs = mock_client.post.await_args.kwargs
    assert post_kwargs["json"] == realm_payload
    assert post_kwargs["headers"]["Authorization"] == "Bearer master-token"


@pytest.mark.asyncio
async def test_ensure_keycloak_realm_treats_conflict_as_success() -> None:
    """Concurrent realm creation returns 409 and is treated as success."""
    discovery_response = MagicMock()
    discovery_response.status_code = 404
    create_response = MagicMock()
    create_response.status_code = 409

    with patch("infrastructure.keycloak.realm_bootstrap.settings", _mock_settings()):
        with patch(
            "infrastructure.keycloak.realm_bootstrap.wait_for_keycloak",
            new_callable=AsyncMock,
        ):
            with patch(
                "infrastructure.keycloak.realm_bootstrap._load_realm_template",
                return_value={"realm": "chatapp"},
            ):
                with patch(
                    "infrastructure.keycloak.realm_bootstrap.get_master_admin_token",
                    new_callable=AsyncMock,
                    return_value="master-token",
                ):
                    with patch("httpx.AsyncClient") as mock_client_cls:
                        mock_client = AsyncMock()
                        mock_client.__aenter__.return_value = mock_client
                        mock_client.__aexit__.return_value = None
                        mock_client.get = AsyncMock(return_value=discovery_response)
                        mock_client.post = AsyncMock(return_value=create_response)
                        mock_client_cls.return_value = mock_client

                        await ensure_keycloak_realm()


@pytest.mark.asyncio
async def test_ensure_keycloak_realm_requires_bootstrap_credentials() -> None:
    """Missing bootstrap admin credentials raise ConfigurationError."""
    with patch(
        "infrastructure.keycloak.realm_bootstrap.settings",
        _mock_settings(bootstrap_admin=""),
    ):
        with pytest.raises(ConfigurationError, match="KEYCLOAK_BOOTSTRAP_ADMIN"):
            await ensure_keycloak_realm()


@pytest.mark.asyncio
async def test_ensure_keycloak_realm_raises_when_keycloak_unavailable() -> None:
    """Keycloak readiness timeout surfaces as ConfigurationError."""
    with patch("infrastructure.keycloak.realm_bootstrap.settings", _mock_settings()):
        with patch(
            "infrastructure.keycloak.realm_bootstrap.wait_for_keycloak",
            new_callable=AsyncMock,
            side_effect=TimeoutError("not ready"),
        ):
            with pytest.raises(ConfigurationError, match="Keycloak is unreachable"):
                await ensure_keycloak_realm()


@pytest.mark.asyncio
async def test_ensure_keycloak_realm_raises_on_master_token_failure() -> None:
    """Failed master admin authentication surfaces as ConfigurationError."""
    discovery_response = MagicMock()
    discovery_response.status_code = 404

    with patch("infrastructure.keycloak.realm_bootstrap.settings", _mock_settings()):
        with patch(
            "infrastructure.keycloak.realm_bootstrap.wait_for_keycloak",
            new_callable=AsyncMock,
        ):
            with patch(
                "infrastructure.keycloak.realm_bootstrap._load_realm_template",
                return_value={"realm": "chatapp"},
            ):
                with patch("httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.get = AsyncMock(return_value=discovery_response)
                    mock_client_cls.return_value = mock_client

                    with patch(
                        "infrastructure.keycloak.realm_bootstrap.get_master_admin_token",
                        new_callable=AsyncMock,
                        side_effect=httpx.HTTPError("auth failed"),
                    ):
                        with pytest.raises(
                            ConfigurationError,
                            match="master admin authentication failed",
                        ):
                            await ensure_keycloak_realm()
