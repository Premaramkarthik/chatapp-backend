"""Tests for Keycloak Google IdP auto-configuration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.keycloak.google_idp_config import (
    _collect_post_logout_redirect_uris,
    _collect_web_redirect_uris,
    build_google_idp_payload,
    ensure_keycloak_google_idp,
)


def _mock_settings(**overrides: object) -> MagicMock:
    settings = MagicMock()
    keycloak = MagicMock()
    keycloak.enabled = overrides.get("enabled", True)
    keycloak.google_client_id = overrides.get("google_client_id", "google-client-id")
    keycloak.google_client_secret_value = overrides.get("google_client_secret", "google-secret")
    keycloak.google_idp_alias = overrides.get("google_idp_alias", "google")
    keycloak.google_idp_hide_on_login_page = overrides.get("google_idp_hide_on_login_page", True)
    keycloak.web_client_id = "chatapp-web"
    keycloak.internal_base = "http://localhost:8180"
    keycloak.realm = "chatapp"
    keycloak.admin_client_id = "chatapp-backend-admin"
    keycloak.admin_client_secret_value = "change-me"
    keycloak.admin_realm_url = "http://localhost:8180/admin/realms/chatapp"
    settings.keycloak = keycloak
    settings.http.timeout_seconds = 5.0
    settings.auth.callback_url = "http://localhost:8000/v1/auth/signin/callback"
    settings.auth.default_post_signin_redirect_url = "http://localhost:5173/home/auth/callback"
    settings.auth.email_verify_redirect_url = "http://localhost:5173/home/verify-email/complete"
    settings.auth.post_logout_redirect_url = "http://localhost:8080/"
    settings.auth.allowed_redirect_origins = ("http://localhost:5173",)
    return settings


def test_build_google_idp_payload_returns_none_without_client_id() -> None:
    """Missing Google client ID yields a no-op payload."""
    with patch(
        "infrastructure.keycloak.google_idp_config.settings",
        _mock_settings(google_client_id=""),
    ):
        assert build_google_idp_payload() is None


def test_build_google_idp_payload_warns_on_missing_secret() -> None:
    """Partial Google OAuth config is ignored instead of failing startup."""
    with patch(
        "infrastructure.keycloak.google_idp_config.settings",
        _mock_settings(google_client_secret=""),
    ):
        assert build_google_idp_payload() is None


def test_build_google_idp_payload_builds_keycloak_shape() -> None:
    """Complete Google settings map to Keycloak identity provider fields."""
    with patch("infrastructure.keycloak.google_idp_config.settings", _mock_settings()):
        payload = build_google_idp_payload()
    assert payload is not None
    assert payload["alias"] == "google"
    assert payload["providerId"] == "google"
    assert payload["config"]["clientId"] == "google-client-id"
    assert payload["config"]["hideOnLoginPage"] == "true"
    assert payload["config"]["prompt"] == "select_account"
    assert payload["firstBrokerLoginFlowAlias"] == "chatapp-google-auto-link"


def test_collect_web_redirect_uris_includes_localhost_mirror() -> None:
    """Redirect URI collection adds localhost/127.0.0.1 variants for dev."""
    with patch("infrastructure.keycloak.google_idp_config.settings", _mock_settings()):
        uris = _collect_web_redirect_uris()
    assert "http://localhost:8000/v1/auth/signin/callback" in uris
    assert "http://127.0.0.1:8000/v1/auth/signin/callback" in uris
    assert "http://localhost:5173/home/auth/callback" in uris


def test_collect_post_logout_redirect_uris_includes_localhost_variants() -> None:
    """Post-logout redirect patterns include localhost and 127.0.0.1 wildcards."""
    with patch("infrastructure.keycloak.google_idp_config.settings", _mock_settings()):
        uris = _collect_post_logout_redirect_uris()
    assert "http://localhost:8080/*" in uris
    assert "http://127.0.0.1:8080/*" in uris


@pytest.mark.asyncio
async def test_ensure_keycloak_google_idp_skips_when_disabled() -> None:
    """Google IdP ensure is a no-op when Keycloak integration is disabled."""
    with patch(
        "infrastructure.keycloak.google_idp_config.settings",
        _mock_settings(enabled=False),
    ):
        with patch(
            "infrastructure.keycloak.google_idp_config._request_with_admin_fallback",
            new_callable=AsyncMock,
        ) as mock_request:
            await ensure_keycloak_google_idp()
    mock_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_keycloak_google_idp_creates_provider() -> None:
    """Google IdP is created when alias does not exist."""
    with patch("infrastructure.keycloak.google_idp_config.settings", _mock_settings()):
        expected_redirects = sorted(_collect_web_redirect_uris())
        expected_origins = sorted(
            {
                "http://localhost:5173",
                "http://localhost:8000",
                "http://127.0.0.1:5173",
                "http://127.0.0.1:8000",
            },
        )
        expected_post_logout = " ".join(sorted(_collect_post_logout_redirect_uris()))

    list_response = MagicMock()
    list_response.raise_for_status = MagicMock()
    list_response.json.return_value = [{"id": "uuid-1", "clientId": "chatapp-web"}]
    detail_response = MagicMock()
    detail_response.raise_for_status = MagicMock()
    detail_response.json.return_value = {
        "clientId": "chatapp-web",
        "redirectUris": expected_redirects,
        "webOrigins": expected_origins,
        "attributes": {"post.logout.redirect.uris": expected_post_logout},
    }
    idp_get_response = MagicMock()
    idp_get_response.status_code = 404
    idp_create_response = MagicMock()
    idp_create_response.raise_for_status = MagicMock()
    flows_response = MagicMock()
    flows_response.raise_for_status = MagicMock()
    flows_response.json.return_value = [{"alias": "chatapp-google-auto-link"}]
    flow_exec_response = MagicMock()
    flow_exec_response.raise_for_status = MagicMock()
    flow_exec_response.json.return_value = [
        {"id": "exec-1", "providerId": "idp-create-user-if-unique", "requirement": "ALTERNATIVE"},
        {"id": "exec-2", "providerId": "idp-auto-link", "requirement": "ALTERNATIVE"},
    ]

    async def fake_request(*, client, method, url, json=None):
        del client, json
        if method == "GET" and url.endswith(
            "/authentication/flows/chatapp-google-auto-link/executions"
        ):
            return flow_exec_response
        if method == "GET" and url.endswith("/authentication/flows"):
            return flows_response
        if method == "GET" and url.endswith("/clients"):
            return list_response
        if method == "GET" and "/clients/uuid-1" in url:
            return detail_response
        if method == "GET" and url.endswith("/identity-provider/instances/google"):
            return idp_get_response
        if method == "POST" and url.endswith("/identity-provider/instances"):
            return idp_create_response
        raise AssertionError(f"Unexpected request: {method} {url}")

    with patch("infrastructure.keycloak.google_idp_config.settings", _mock_settings()):
        with patch(
            "infrastructure.keycloak.google_idp_config._request_with_admin_fallback",
            side_effect=fake_request,
        ):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client_cls.return_value = mock_client

                await ensure_keycloak_google_idp()

    idp_create_response.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_keycloak_google_idp_updates_existing_provider() -> None:
    """Google IdP is updated when alias already exists."""
    with patch("infrastructure.keycloak.google_idp_config.settings", _mock_settings()):
        expected_redirects = sorted(_collect_web_redirect_uris())
        expected_origins = sorted(
            {
                "http://localhost:5173",
                "http://localhost:8000",
                "http://127.0.0.1:5173",
                "http://127.0.0.1:8000",
            },
        )
        expected_post_logout = " ".join(sorted(_collect_post_logout_redirect_uris()))

    list_response = MagicMock()
    list_response.raise_for_status = MagicMock()
    list_response.json.return_value = [{"id": "uuid-1", "clientId": "chatapp-web"}]
    detail_response = MagicMock()
    detail_response.raise_for_status = MagicMock()
    detail_response.json.return_value = {
        "clientId": "chatapp-web",
        "redirectUris": expected_redirects,
        "webOrigins": expected_origins,
        "attributes": {"post.logout.redirect.uris": expected_post_logout},
    }
    idp_get_response = MagicMock()
    idp_get_response.raise_for_status = MagicMock()
    idp_get_response.status_code = 200
    idp_get_response.json.return_value = {
        "alias": "google",
        "providerId": "google",
        "config": {"clientId": "old-id", "clientSecret": "old-secret"},
    }
    idp_put_response = MagicMock()
    idp_put_response.raise_for_status = MagicMock()
    flows_response = MagicMock()
    flows_response.raise_for_status = MagicMock()
    flows_response.json.return_value = [{"alias": "chatapp-google-auto-link"}]
    flow_exec_response = MagicMock()
    flow_exec_response.raise_for_status = MagicMock()
    flow_exec_response.json.return_value = [
        {"id": "exec-1", "providerId": "idp-create-user-if-unique", "requirement": "ALTERNATIVE"},
        {"id": "exec-2", "providerId": "idp-auto-link", "requirement": "ALTERNATIVE"},
    ]

    async def fake_request(*, client, method, url, json=None):
        del client
        if method == "GET" and url.endswith(
            "/authentication/flows/chatapp-google-auto-link/executions"
        ):
            return flow_exec_response
        if method == "GET" and url.endswith("/authentication/flows"):
            return flows_response
        if method == "GET" and url.endswith("/clients"):
            return list_response
        if method == "GET" and "/clients/uuid-1" in url:
            return detail_response
        if method == "GET" and url.endswith("/identity-provider/instances/google"):
            return idp_get_response
        if method == "PUT" and url.endswith("/identity-provider/instances/google"):
            assert json is not None
            assert json["config"]["clientId"] == "google-client-id"
            assert json["config"]["prompt"] == "select_account"
            assert json["firstBrokerLoginFlowAlias"] == "chatapp-google-auto-link"
            return idp_put_response
        raise AssertionError(f"Unexpected request: {method} {url}")

    with patch("infrastructure.keycloak.google_idp_config.settings", _mock_settings()):
        with patch(
            "infrastructure.keycloak.google_idp_config._request_with_admin_fallback",
            side_effect=fake_request,
        ):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client_cls.return_value = mock_client

                await ensure_keycloak_google_idp()

    idp_put_response.raise_for_status.assert_called_once()
