"""Keycloak auth client unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from domains.auth.keycloak_client import (
    KeycloakAuthClient,
    _authentication_error_from_token_response,
)


def test_authorization_url_includes_select_account_for_social_idp() -> None:
    client = KeycloakAuthClient()
    url = client.authorization_url(
        state="state",
        nonce="nonce",
        code_challenge="challenge",
        redirect_uri="http://localhost:8000/v1/auth/signin/callback",
        identity_provider="google",
    )
    assert "prompt=select_account" in url
    assert "kc_idp_hint=google" in url


def test_authorization_url_omits_select_account_without_idp() -> None:
    client = KeycloakAuthClient()
    url = client.authorization_url(
        state="state",
        nonce="nonce",
        code_challenge="challenge",
        redirect_uri="http://localhost:8000/v1/auth/signin/callback",
    )
    assert "prompt=select_account" not in url


@pytest.mark.asyncio
async def test_send_verify_email_includes_redirect_uri_when_configured() -> None:
    client = KeycloakAuthClient()
    mock_admin = AsyncMock()

    with (
        patch.object(client, "_admin", mock_admin),
        patch(
            "infrastructure.keycloak.admin_client.settings.auth.email_verify_redirect_url",
            "http://localhost:5173/home/verify-email/complete",
        ),
    ):
        await client.send_verify_email(user_id="user-123")

    mock_admin.send_verify_email.assert_awaited_once_with(user_id="user-123")


def test_token_error_maps_unverified_account_to_email_verification_required() -> None:
    response = MagicMock()
    response.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Account is not fully set up",
    }
    exc = httpx.HTTPStatusError(
        "bad request",
        request=MagicMock(),
        response=response,
    )
    error = _authentication_error_from_token_response(exc, grant_type="password")
    assert error.code == "email_verification_required"


def test_token_error_maps_invalid_credentials() -> None:
    response = MagicMock()
    response.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Invalid user credentials",
    }
    exc = httpx.HTTPStatusError(
        "bad request",
        request=MagicMock(),
        response=response,
    )
    error = _authentication_error_from_token_response(exc, grant_type="password")
    assert error.code == "authentication_error"
    assert error.message == "Invalid email or password"
