"""Role architecture guard and session enrichment tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domains.users.user import User
from main import app
from v1.dependencies.auth import get_current_principal
from v1.schemas.principal import KeycloakPrincipal


def _user(*, account_mode: str) -> User:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return User(
        id=str(uuid4()),
        keycloak_sub=f"{account_mode}-sub",
        email=f"{account_mode}@example.com",
        display_name=f"{account_mode.title()} User",
        status="active",
        account_mode=account_mode,
        email_verified=True,
        created_via="email",
        created_at=now,
        updated_at=now,
    )


def _principal(user: User) -> KeycloakPrincipal:
    return KeycloakPrincipal(
        sub=user.keycloak_sub,
        email=user.email,
        email_verified=True,
        display_name=user.display_name,
        preferred_username=user.email,
        identity_provider="email",
        roles=["trip:create", "trip:join", "message:send"],
    )


def test_connector_gets_403_on_explorer_trip_create(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connectors must not create explorer trips even with trip:create capability."""
    user = _user(account_mode="connector")

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/explorers/trips",
                json={
                    "title": "Trip",
                    "destinations": [{"country_code": "US", "is_primary": True}],
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_explorer_gets_403_on_connector_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explorers must not run connector search even with trip:join capability."""
    user = _user(account_mode="explorer")

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/explorers/search?destination_country=US")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_session_includes_profile_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Session response exposes onboarding_complete and profile_exists."""
    user = _user(account_mode="explorer")

    class FakeBootstrapUser:
        async def execute(self, command, *, request_id: str | None = None) -> User:
            return user

    async def fake_build(user: User) -> dict:
        payload = user.to_dict()
        payload["onboarding_complete"] = user.onboarding_completed_at is not None
        payload["profile_exists"] = True
        return payload

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    from v1.dependencies.container import get_bootstrap_user_use_case

    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    app.dependency_overrides[get_bootstrap_user_use_case] = lambda: FakeBootstrapUser()
    monkeypatch.setattr("v1.routers.auth.build_user_response", fake_build)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/auth/session")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["onboarding_complete"] is False
    assert body["profile_exists"] is True
