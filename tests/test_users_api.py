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

    async def fake_build_user_response(user: User) -> dict:
        payload = user.to_dict()
        payload["onboarding_complete"] = user.onboarding_completed_at is not None
        payload["profile_exists"] = user.account_mode is not None
        return payload

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
    monkeypatch.setattr("v1.routers.users.build_user_response", fake_build_user_response)
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/v1/users/account-mode",
                json={"account_mode": "connector"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert updated_mode == "connector"
    assert response.json()["account_mode"] == "connector"


def test_update_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated users can update display name."""
    updated_name: str | None = None
    keycloak_sync: dict[str, str] | None = None
    snapshot_rebuilt_for: str | None = None

    class FakeUserRepository:
        async def update_display_name(self, *, user_id: str, display_name: str) -> User:
            nonlocal updated_name
            updated_name = display_name
            now = datetime(2026, 1, 1, tzinfo=UTC)
            return User(
                id=user_id,
                keycloak_sub="google-sub-123",
                email="user@example.com",
                display_name=display_name,
                status="active",
                account_mode="explorer",
                email_verified=True,
                created_via="google",
                created_at=now,
                updated_at=now,
            )

    class FakeDiscoveryRepository:
        async def rebuild_snapshot(self, user_id: str) -> dict:
            nonlocal snapshot_rebuilt_for
            snapshot_rebuilt_for = user_id
            return {}

    class FakeAuthService:
        async def sync_display_name(self, *, keycloak_sub: str, display_name: str) -> None:
            nonlocal keycloak_sync
            keycloak_sync = {"keycloak_sub": keycloak_sub, "display_name": display_name}

    async def fake_build_user_response(user: User) -> dict:
        payload = user.to_dict()
        payload["onboarding_complete"] = user.onboarding_completed_at is not None
        payload["profile_exists"] = user.account_mode is not None
        return payload

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
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    monkeypatch.setattr("v1.routers.users.PostgresUserRepository", FakeUserRepository)
    monkeypatch.setattr("v1.routers.users.PostgresDiscoveryRepository", FakeDiscoveryRepository)
    monkeypatch.setattr("v1.routers.users.build_user_response", fake_build_user_response)
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/v1/users/display-name",
                json={"display_name": "New Name"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert updated_name == "New Name"
    assert response.json()["display_name"] == "New Name"
    assert keycloak_sync == {"keycloak_sub": "google-sub-123", "display_name": "New Name"}
    assert snapshot_rebuilt_for is not None


def test_update_display_name_rejects_short_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Display name must be at least two characters after normalization."""
    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = _fake_principal
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/v1/users/display-name",
                json={"display_name": "A"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_update_display_name_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unauthenticated requests are rejected."""
    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        True,
    )
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/v1/users/display-name",
                json={"display_name": "Valid Name"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_delete_my_account_returns_local_and_remote_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated users can delete their account."""
    deleted = False

    class FakeAuthService:
        async def delete_account(self, *, principal_sub: str, request) -> dict:
            nonlocal deleted
            deleted = True
            assert principal_sub == "google-sub-123"
            return {
                "local_revocation": "complete",
                "remote_termination": "complete",
                "operation_id": "op",
            }

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

    assert response.status_code == 200
    assert response.json()["local_revocation"] == "complete"
    assert deleted is True
