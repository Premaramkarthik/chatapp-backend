"""Current-user route tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domains.users.user import BootstrapUserCommand, User
from main import app
from v1.dependencies.auth import get_current_principal
from v1.dependencies.container import get_auth_service, get_bootstrap_user_use_case
from v1.schemas.principal import KeycloakPrincipal


class FakeBootstrapUser:
    """Return a pre-onboarding user with no account_mode set."""

    async def execute(
        self,
        command: BootstrapUserCommand,
        *,
        request_id: str | None = None,
    ) -> User:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        return User(
            id=str(uuid4()),
            keycloak_sub=command.keycloak_sub,
            email=command.email,
            display_name=command.display_name,
            status="pending_profile_setup",
            account_mode=None,
            email_verified=True,
            created_via="google",
            created_at=now,
            updated_at=now,
        )


def _fake_principal() -> KeycloakPrincipal:
    return KeycloakPrincipal(
        sub="google-sub-123",
        email="user@example.com",
        email_verified=True,
        display_name="Google User",
        preferred_username="user@example.com",
        identity_provider="google",
        roles=["profile:update"],
    )


def test_auth_session_returns_null_account_mode_for_pending_profile_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: OAuth users before onboarding must not 500 on session restore."""
    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = _fake_principal
    app.dependency_overrides[get_bootstrap_user_use_case] = lambda: FakeBootstrapUser()
    try:
        with TestClient(app) as client:
            response = client.get("/v1/auth/session")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_profile_setup"
    assert body["account_mode"] is None
    assert body["email"] == "user@example.com"


def test_update_account_mode_without_profile_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated users can update account mode without profile:update in JWT."""
    updated_mode: str | None = None

    class FakeUserRepository:
        async def update_account_mode(self, *, keycloak_sub: str, account_mode: str) -> User:
            nonlocal updated_mode
            updated_mode = account_mode
            now = datetime(2026, 1, 1, tzinfo=UTC)
            return User(
                id=str(uuid4()),
                keycloak_sub=keycloak_sub,
                email="user@example.com",
                display_name="Google User",
                status="active",
                account_mode=account_mode,
                email_verified=True,
                created_via="google",
                created_at=now,
                updated_at=now,
            )

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = lambda: KeycloakPrincipal(
        sub="google-sub-123",
        email="user@example.com",
        email_verified=True,
        display_name="Google User",
        preferred_username="user@example.com",
        identity_provider="google",
        roles=[],
    )
    app.dependency_overrides[get_bootstrap_user_use_case] = lambda: FakeBootstrapUser()
    monkeypatch.setattr("v1.routers.users.PostgresUserRepository", FakeUserRepository)
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/v1/users/account-mode",
                json={"account_mode": "messenger"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert updated_mode == "messenger"
    assert response.json()["account_mode"] == "messenger"


def test_delete_my_account_returns_204(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated users can delete their account."""
    deleted = False

    class FakeAuthService:
        async def delete_account(self, *, principal_sub: str, request) -> None:
            nonlocal deleted
            deleted = True
            assert principal_sub == "google-sub-123"

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = _fake_principal
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    try:
        with TestClient(app) as client:
            response = client.delete("/v1/users/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert deleted is True
