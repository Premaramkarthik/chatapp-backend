"""Tests for Keycloak SMTP auto-configuration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from infrastructure.keycloak.smtp_config import build_smtp_server_payload, ensure_keycloak_smtp


def _mock_settings(**overrides: object) -> MagicMock:
    settings = MagicMock()
    keycloak = MagicMock()
    keycloak.enabled = overrides.get("enabled", True)
    keycloak.smtp_host = overrides.get("smtp_host", "smtp.gmail.com")
    keycloak.smtp_port = "587"
    keycloak.smtp_from = overrides.get("smtp_from", "noreply@example.com")
    keycloak.smtp_from_display_name = "ChatApp"
    keycloak.smtp_user = overrides.get("smtp_user", "noreply@example.com")
    keycloak.smtp_password_value = overrides.get("smtp_password", "secret")
    keycloak.smtp_starttls = "true"
    keycloak.smtp_ssl = "false"
    keycloak.internal_base = "http://localhost:8180"
    keycloak.realm = "chatapp"
    keycloak.admin_client_id = "chatapp-backend-admin"
    keycloak.admin_client_secret_value = "change-me"
    keycloak.admin_realm_url = "http://localhost:8180/admin/realms/chatapp"
    settings.keycloak = keycloak
    settings.http.timeout_seconds = 5.0
    return settings


def test_build_smtp_server_payload_returns_none_without_host() -> None:
    """Missing SMTP host yields a no-op payload."""
    with patch("infrastructure.keycloak.smtp_config.settings", _mock_settings(smtp_host="")):
        assert build_smtp_server_payload() is None


def test_build_smtp_server_payload_warns_on_incomplete_config() -> None:
    """Partial SMTP config is ignored instead of failing startup."""
    with patch("infrastructure.keycloak.smtp_config.settings", _mock_settings(smtp_user="")):
        assert build_smtp_server_payload() is None


def test_build_smtp_server_payload_builds_keycloak_shape() -> None:
    """Complete SMTP settings map to Keycloak smtpServer fields."""
    with patch("infrastructure.keycloak.smtp_config.settings", _mock_settings()):
        payload = build_smtp_server_payload()
    assert payload is not None
    assert payload["host"] == "smtp.gmail.com"
    assert payload["auth"] == "true"
    assert payload["user"] == "noreply@example.com"


@pytest.mark.asyncio
async def test_ensure_keycloak_smtp_skips_when_disabled() -> None:
    """SMTP ensure is a no-op when Keycloak integration is disabled."""
    with patch("infrastructure.keycloak.smtp_config.settings", _mock_settings(enabled=False)):
        with patch(
            "infrastructure.keycloak.smtp_config._client_credentials_token",
            new_callable=AsyncMock,
        ) as mock_token:
            await ensure_keycloak_smtp()
    mock_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_keycloak_smtp_applies_with_service_account() -> None:
    """SMTP settings are merged into the realm via Admin REST API."""
    get_response = MagicMock()
    get_response.raise_for_status = MagicMock()
    get_response.json.return_value = {"realm": "chatapp", "smtpServer": {}}
    put_response = MagicMock()
    put_response.raise_for_status = MagicMock()

    with patch("infrastructure.keycloak.smtp_config.settings", _mock_settings()):
        with patch(
            "infrastructure.keycloak.smtp_config._client_credentials_token",
            new_callable=AsyncMock,
            return_value="service-token",
        ):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get = AsyncMock(return_value=get_response)
                mock_client.put = AsyncMock(return_value=put_response)
                mock_client_cls.return_value = mock_client

                await ensure_keycloak_smtp()

    mock_client.put.assert_awaited_once()
    put_payload = mock_client.put.await_args.kwargs["json"]
    assert put_payload["smtpServer"]["host"] == "smtp.gmail.com"


@pytest.mark.asyncio
async def test_ensure_keycloak_smtp_falls_back_to_master_admin_on_403() -> None:
    """Master admin token is used when the service account lacks manage-realm."""
    get_response = MagicMock()
    get_response.raise_for_status = MagicMock()
    get_response.json.return_value = {"realm": "chatapp"}
    put_ok = MagicMock()
    put_ok.raise_for_status = MagicMock()
    put_forbidden = MagicMock()
    put_forbidden.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Forbidden",
        request=MagicMock(),
        response=MagicMock(status_code=403),
    )

    with patch("infrastructure.keycloak.smtp_config.settings", _mock_settings()):
        with patch(
            "infrastructure.keycloak.smtp_config._client_credentials_token",
            new_callable=AsyncMock,
            return_value="service-token",
        ):
            with patch(
                "infrastructure.keycloak.smtp_config.get_master_admin_token",
                new_callable=AsyncMock,
                return_value="master-token",
            ):
                with patch("httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.__aexit__.return_value = None
                    mock_client.get = AsyncMock(return_value=get_response)
                    mock_client.put = AsyncMock(side_effect=[put_forbidden, put_ok])
                    mock_client_cls.return_value = mock_client

                    await ensure_keycloak_smtp()

    assert mock_client.put.await_count == 2
    second_headers = mock_client.put.await_args_list[1].kwargs["headers"]
    assert second_headers["Authorization"] == "Bearer master-token"
