"""Public profile API tests."""

from __future__ import annotations

from dataclasses import replace
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


@pytest.fixture
def profile_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, User]:
    viewer = _user(account_mode="connector")

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return viewer

    monkeypatch.setattr("v1.middleware.authentication.settings.middleware.auth_enabled", False)
    app.dependency_overrides[get_current_principal] = lambda: KeycloakPrincipal(
        sub=viewer.keycloak_sub,
        email=viewer.email,
        email_verified=True,
        display_name=viewer.display_name,
        preferred_username=viewer.email,
        identity_provider="email",
        roles=["profile:update"],
    )
    monkeypatch.setattr("v1.routers.users.PostgresUserRepository", FakeUserRepository)
    with TestClient(app) as client:
        yield client, viewer
    app.dependency_overrides.clear()


def test_public_profile_explorer_happy_path(
    profile_client: tuple[TestClient, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, viewer = profile_client
    target_id = str(uuid4())
    target = replace(_user(account_mode="explorer"), id=target_id)

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return viewer

        async def get_by_id(self, user_id: str) -> User | None:
            if user_id == target_id:
                return target
            return None

    async def fake_blocked(_self, a: str, b: str) -> bool:
        return False

    async def fake_fetch(_self, user_ids: list[str]) -> list[dict]:
        return [
            {
                "user_id": target_id,
                "display_name": "Explorer One",
                "headline": "On the road",
                "avatar_url": None,
                "destination_country_iso": "US",
                "destination_city_name": "NYC",
                "current_country_iso": "GB",
                "languages": ["en"],
                "interests": ["food"],
                "connection_availability": "open",
                "visibility": "discoverable",
                "last_active_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
        ]

    monkeypatch.setattr("v1.routers.users.PostgresUserRepository", FakeUserRepository)
    monkeypatch.setattr("v1.routers.users.PostgresMatchingRepository.is_blocked", fake_blocked)
    monkeypatch.setattr(
        "v1.routers.users.PostgresDiscoveryRepository.fetch_public_by_ids",
        fake_fetch,
    )

    response = client.get(f"/v1/users/{target_id}/public-profile")
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Explorer One"
    assert body["interests"] == ["food"]


def test_public_profile_blocked_returns_404(
    profile_client: tuple[TestClient, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, viewer = profile_client
    target_id = str(uuid4())
    target = replace(_user(account_mode="explorer"), id=target_id)

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return viewer

        async def get_by_id(self, user_id: str) -> User | None:
            return target if user_id == target_id else None

    async def fake_blocked(_self, a: str, b: str) -> bool:
        return True

    monkeypatch.setattr("v1.routers.users.PostgresUserRepository", FakeUserRepository)
    monkeypatch.setattr("v1.routers.users.PostgresMatchingRepository.is_blocked", fake_blocked)

    response = client.get(f"/v1/users/{target_id}/public-profile")
    assert response.status_code == 404
