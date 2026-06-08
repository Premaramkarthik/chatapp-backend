"""Tests for Keycloak startup validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.keycloak.startup_validation import validate_keycloak_startup
from v1.utils.base import ConfigurationError


@pytest.mark.asyncio
async def test_validate_keycloak_startup_ok() -> None:
    """Validation passes when discovery, token, clients, and roles exist."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("infrastructure.keycloak.startup_validation.settings") as mock_settings:
        mock_settings.keycloak.enabled = True
        mock_settings.http.timeout_seconds = 5.0
        mock_settings.keycloak.well_known_url = "http://kc/.well-known"
        mock_settings.keycloak.admin_realm_url = "http://kc/admin/realms/chatapp"
        mock_settings.keycloak.realm = "chatapp"
        mock_settings.keycloak.web_client_id = "chatapp-web"
        mock_settings.keycloak.audience = "chatapp-api"
        mock_settings.keycloak.google_idp_alias = ""
        mock_settings.auth.default_signup_roles = ["profile:update"]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with patch(
                "infrastructure.keycloak.startup_validation.keycloak_admin_client"
            ) as mock_admin:
                mock_admin.get_admin_token = AsyncMock(return_value="token")
                mock_admin.client_exists = AsyncMock(return_value=True)
                mock_admin.client_role_exists = AsyncMock(return_value=True)

                await validate_keycloak_startup()


@pytest.mark.asyncio
async def test_validate_keycloak_startup_missing_client() -> None:
    """Missing client raises ConfigurationError."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("infrastructure.keycloak.startup_validation.settings") as mock_settings:
        mock_settings.keycloak.enabled = True
        mock_settings.http.timeout_seconds = 5.0
        mock_settings.keycloak.well_known_url = "http://kc/.well-known"
        mock_settings.keycloak.admin_realm_url = "http://kc/admin/realms/chatapp"
        mock_settings.keycloak.realm = "chatapp"
        mock_settings.keycloak.web_client_id = "chatapp-web"
        mock_settings.keycloak.audience = "chatapp-api"
        mock_settings.keycloak.google_idp_alias = ""
        mock_settings.auth.default_signup_roles = []

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with patch(
                "infrastructure.keycloak.startup_validation.keycloak_admin_client"
            ) as mock_admin:
                mock_admin.get_admin_token = AsyncMock(return_value="token")
                mock_admin.client_exists = AsyncMock(return_value=False)

                with pytest.raises(ConfigurationError):
                    await validate_keycloak_startup()
