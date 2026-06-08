"""Unit tests for signup step-1 Keycloak provisioning."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from domains.users.user import User, UserStatus

_provision_path = (
    Path(__file__).resolve().parents[1] / "domains" / "utils" / "signup_start_provision.py"
)
_spec = importlib.util.spec_from_file_location("signup_start_provision", _provision_path)
assert _spec and _spec.loader
_provision_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_provision_module)
SignupStartProvisioner = _provision_module.SignupStartProvisioner


def _pending_user(*, keycloak_sub: str | None = None) -> User:
    return User(
        id="user-id",
        email="user@example.com",
        status=UserStatus.PENDING_VERIFICATION.value,
        account_mode=None,
        display_name=None,
        keycloak_sub=keycloak_sub,
        email_verified=False,
        created_via="email",
        onboarding_completed_at=None,
        last_verification_sent_at=None,
        verification_send_count=0,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_provision_clears_required_actions_before_verify_email() -> None:
    """Signup step 1 must not leave Keycloak execute-actions on the verify link."""
    keycloak = AsyncMock()
    keycloak.create_user = AsyncMock(return_value="kc-sub")
    keycloak.set_user_password = AsyncMock()
    keycloak.clear_required_actions = AsyncMock()
    keycloak.send_verification_email = AsyncMock()

    user_repository = AsyncMock()
    user_repository.link_keycloak_subject = AsyncMock(
        return_value=_pending_user(keycloak_sub="kc-sub"),
    )
    user_repository.mark_verification_sent = AsyncMock()

    auth_repository = AsyncMock()
    auth_repository.write_outbox_event = AsyncMock()
    auth_repository.create_signup_session = AsyncMock()

    provisioner = SignupStartProvisioner(
        user_repository=user_repository,
        auth_repository=auth_repository,
        keycloak=keycloak,
    )

    await provisioner.provision(
        user=_pending_user(),
        email="user@example.com",
        password="SecurePassw0rd!12",
        request_id="req-1",
    )

    keycloak.clear_required_actions.assert_awaited_once_with(user_id="kc-sub")
    keycloak.send_verification_email.assert_awaited_once_with(user_id="kc-sub")
    keycloak.create_user.assert_awaited_once()
    assert keycloak.create_user.await_args.kwargs["required_actions"] == []
