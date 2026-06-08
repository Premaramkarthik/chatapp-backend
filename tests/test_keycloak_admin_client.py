"""Tests for KeycloakAdminClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from infrastructure.keycloak.admin_client import KeycloakAdminClient
from v1.utils.base import KeycloakIntegrationError


@pytest.mark.asyncio
async def test_create_user_returns_existing_on_conflict() -> None:
    """409 responses fall back to email lookup."""
    admin = KeycloakAdminClient()
    admin.get_admin_token = AsyncMock(return_value="token")  # type: ignore[method-assign]
    admin.find_user_by_email = AsyncMock(return_value="existing-id")  # type: ignore[method-assign]
    admin.assign_client_roles = AsyncMock()  # type: ignore[method-assign]

    response = MagicMock()
    response.status_code = 409
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "conflict",
        request=httpx.Request("POST", "http://kc/users"),
        response=response,
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=response)
    admin._http_client = AsyncMock(return_value=mock_client)  # type: ignore[method-assign]

    user_id = await admin.create_user(email="a@example.com", display_name="A")
    assert user_id == "existing-id"


@pytest.mark.asyncio
async def test_delete_user_calls_admin_api() -> None:
    """delete_user issues DELETE to Keycloak Admin REST."""
    admin = KeycloakAdminClient()
    admin._request = AsyncMock()  # type: ignore[method-assign]

    await admin.delete_user("kc-user-id")
    admin._request.assert_awaited_once()
    assert admin._request.await_args.kwargs["operation"] == "delete_user"


@pytest.mark.asyncio
async def test_client_exists_false_when_missing() -> None:
    """client_exists returns False when client lookup fails."""
    admin = KeycloakAdminClient()
    admin._client_uuid = AsyncMock(  # type: ignore[method-assign]
        side_effect=KeycloakIntegrationError("missing", context={"client_id": "x"}),
    )
    assert await admin.client_exists("missing-client") is False


@pytest.mark.asyncio
async def test_clear_required_actions_clears_user_fields() -> None:
    """clear_required_actions issues an empty requiredActions update."""
    admin = KeycloakAdminClient()
    admin.update_user = AsyncMock()  # type: ignore[method-assign]

    await admin.clear_required_actions(user_id="user-123")

    admin.update_user.assert_awaited_once_with(
        user_id="user-123",
        fields={"requiredActions": []},
    )


@pytest.mark.asyncio
async def test_send_account_setup_email_is_verify_only() -> None:
    """Legacy setup email path must not trigger execute-actions wizard."""
    admin = KeycloakAdminClient()
    admin.clear_required_actions = AsyncMock()  # type: ignore[method-assign]
    admin.send_verify_email = AsyncMock()  # type: ignore[method-assign]

    await admin.send_account_setup_email(user_id="user-123")

    admin.clear_required_actions.assert_awaited_once_with(user_id="user-123")
    admin.send_verify_email.assert_awaited_once_with(user_id="user-123")
