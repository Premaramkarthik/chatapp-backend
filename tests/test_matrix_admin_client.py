"""Unit tests for SynapseAdminClient auth lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from infrastructure.matrix.admin import SynapseAdminClient
from infrastructure.matrix.startup_validation import validate_matrix_startup
from v1.utils.base import ConfigurationError, MatrixIntegrationError


def _mock_settings(**overrides: object) -> MagicMock:
    matrix = MagicMock()
    matrix.homeserver_url = "http://synapse:8008"
    matrix.server_name = "matrix.local"
    matrix.service_admin_user = "connectcarry-admin"
    matrix.service_admin_password_value = "secret"
    matrix.service_admin_mxid = "@connectcarry-admin:matrix.local"
    matrix.admin_token_value = ""
    matrix.enabled = True
    for key, value in overrides.items():
        setattr(matrix, key, value)
    settings = MagicMock()
    settings.matrix = matrix
    settings.http.timeout_seconds = 5.0
    return settings


@pytest.mark.asyncio
async def test_service_admin_login_caches_token() -> None:
    """Login stores access_token in memory for subsequent calls."""
    login_response = MagicMock()
    login_response.raise_for_status = MagicMock()
    login_response.json.return_value = {"access_token": "syt_login"}

    with patch("infrastructure.matrix.admin.settings", _mock_settings()):
        client = SynapseAdminClient(admin_token="")
        with patch("httpx.AsyncClient") as mock_client_cls:
            http = AsyncMock()
            http.__aenter__.return_value = http
            http.__aexit__.return_value = None
            http.post = AsyncMock(return_value=login_response)
            mock_client_cls.return_value = http

            token = await client.login()
            assert token == "syt_login"
            assert await client.get_token() == "syt_login"
            assert http.post.await_count == 1


@pytest.mark.asyncio
async def test_static_admin_token_skips_login() -> None:
    """MATRIX_ADMIN_TOKEN override bypasses password login."""
    client = SynapseAdminClient(admin_token="syt_override")
    with patch("infrastructure.matrix.admin.settings", _mock_settings()):
        with patch("httpx.AsyncClient") as mock_client_cls:
            http = AsyncMock()
            http.__aenter__.return_value = http
            http.__aexit__.return_value = None
            mock_client_cls.return_value = http

            assert await client.get_token() == "syt_override"
            http.post.assert_not_called()


@pytest.mark.asyncio
async def test_admin_request_retries_after_401() -> None:
    """First 401 triggers retry_login and one retry succeeds."""
    login_response = MagicMock()
    login_response.raise_for_status = MagicMock()
    login_response.json.side_effect = [
        {"access_token": "old"},
        {"access_token": "fresh"},
    ]

    unauthorized = MagicMock()
    unauthorized.status_code = 401
    unauthorized.content = b"unauthorized"

    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.content = b'{"users":[]}'
    ok_response.json.return_value = {"users": []}
    ok_response.raise_for_status = MagicMock()

    with patch("infrastructure.matrix.admin.settings", _mock_settings()):
        client = SynapseAdminClient(admin_token="")
        with patch("httpx.AsyncClient") as mock_client_cls:
            http = AsyncMock()
            http.__aenter__.return_value = http
            http.__aexit__.return_value = None
            http.post = AsyncMock(return_value=login_response)
            http.request = AsyncMock(side_effect=[unauthorized, ok_response])
            mock_client_cls.return_value = http

            users = await client.search_users(search_term="alice")
            assert users == []
            assert http.post.await_count == 2
            assert http.request.await_count == 2


@pytest.mark.asyncio
async def test_admin_request_403_does_not_retry_login() -> None:
    """403 fails immediately without a second login attempt."""
    login_response = MagicMock()
    login_response.raise_for_status = MagicMock()
    login_response.json.return_value = {"access_token": "tok"}

    forbidden = MagicMock()
    forbidden.status_code = 403
    forbidden.content = b"forbidden"
    forbidden.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "forbidden",
            request=MagicMock(),
            response=forbidden,
        ),
    )

    with patch("infrastructure.matrix.admin.settings", _mock_settings()):
        client = SynapseAdminClient(admin_token="")
        with patch("httpx.AsyncClient") as mock_client_cls:
            http = AsyncMock()
            http.__aenter__.return_value = http
            http.__aexit__.return_value = None
            http.post = AsyncMock(return_value=login_response)
            http.request = AsyncMock(return_value=forbidden)
            mock_client_cls.return_value = http

            with pytest.raises(MatrixIntegrationError, match="Synapse admin request failed"):
                await client.search_users(search_term="bob")
            assert http.post.await_count == 1


@pytest.mark.asyncio
async def test_validate_matrix_startup_raises_on_login_failure() -> None:
    """Startup validation fails fast when service admin login fails."""
    with patch("infrastructure.matrix.startup_validation.settings") as mock_settings:
        mock_settings.matrix.enabled = True
        with patch("infrastructure.matrix.startup_validation.synapse_admin_client") as mock_client:
            mock_client.login = AsyncMock(
                side_effect=MatrixIntegrationError("Matrix service admin login failed"),
            )
            with pytest.raises(
                ConfigurationError, match="Matrix service admin authentication failed"
            ):
                await validate_matrix_startup()
