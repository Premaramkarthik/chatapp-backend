"""Standard Keycloak session checks and scoped remote logout."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from infrastructure.keycloak.session_control import SessionControl
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import AuthenticationError


@pytest.mark.asyncio
async def test_remote_session_revocation_is_detected():
    control = SessionControl()
    control.request = AsyncMock(return_value={"enabled": True})
    control.sessions = AsyncMock(return_value=[])
    with pytest.raises(AuthenticationError):
        await control.check(KeycloakPrincipal(sub="user", sid="old-session"))


@pytest.mark.asyncio
async def test_active_session_is_accepted_without_custom_claims():
    control = SessionControl()
    control.request = AsyncMock(return_value={"enabled": True})
    control.sessions = AsyncMock(return_value=[{"id": "current"}])
    await control.check(KeycloakPrincipal(sub="user", sid="current"))


@pytest.mark.asyncio
async def test_provider_outage_fails_closed():
    control = SessionControl()
    control.request = AsyncMock(side_effect=HTTPException(503))
    with pytest.raises(HTTPException) as exc:
        await control.check(KeycloakPrincipal(sub="user", sid="current"))
    assert exc.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["current", "all"])
async def test_logout_retries_only_stored_session_ids(scope):
    control = SessionControl()
    control.request = AsyncMock()
    await control.terminate(
        {"scope": scope, "session_ids": ["old", "keep"], "preserve_session_id": "keep"}
    )
    assert control.request.await_count == 2
    for call in control.request.await_args_list:
        assert call.args == ("DELETE", "/sessions/old")
    assert control.request.await_args_list[0].kwargs["params"] == {"isOffline": "false"}
    assert control.request.await_args_list[1].kwargs["params"] == {"isOffline": "true"}


@pytest.mark.asyncio
async def test_account_deletion_uses_standard_user_endpoint():
    control = SessionControl()
    control.request = AsyncMock()
    await control.terminate({"scope": "delete_account", "subject": "user"})
    control.request.assert_awaited_once_with("DELETE", "/users/user")
