"""Explorer search API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domains.users.user import User
from main import app
from v1.dependencies.auth import get_current_principal
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import TypesenseIntegrationError


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


def test_explorer_connector_route_search_uses_postgres_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explorer connector route search returns postgres fallback rows."""
    user = _user(account_mode="explorer")
    connector_id = str(uuid4())

    class FakeDiscovery:
        async def list_discoverable_connectors(self, **kwargs: object) -> tuple[list[dict], int]:
            return (
                [
                    {
                        "user_id": connector_id,
                        "display_name": "Connector One",
                        "bio": "Local guide",
                        "avatar_url": None,
                        "home_country_label": "United States",
                        "home_city_label": "Austin",
                        "preferred_destination_countries": ["US"],
                        "last_active_at": None,
                    }
                ],
                1,
            )

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    monkeypatch.setattr(
        "v1.routers.explorer_search.PostgresConnectorDiscoveryRepository",
        FakeDiscovery,
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/explorers/search/connectors?destination_country=US")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["hits"][0]["display_name"] == "Connector One"


def test_explorer_username_search_requires_min_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explorer username search rejects queries shorter than two characters."""
    user = _user(account_mode="explorer")

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/explorers/search/users?q=x")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_explorer_username_search_falls_back_to_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explorer username search uses postgres when Typesense fails."""
    user = _user(account_mode="explorer")
    connector_id = str(uuid4())

    class FakeDiscovery:
        async def search_by_username(self, **kwargs: object) -> tuple[list[dict], int]:
            return (
                [
                    {
                        "user_id": connector_id,
                        "display_name": "Karthik Connector",
                        "bio": "Local help",
                        "avatar_url": None,
                        "home_country_label": "India",
                        "home_city_label": "Chennai",
                        "preferred_destination_countries": ["IN"],
                    }
                ],
                1,
            )

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    async def boom(self, **kwargs: object) -> dict:
        raise TypesenseIntegrationError("connection refused")

    monkeypatch.setattr("v1.middleware.authentication.settings.middleware.auth_enabled", False)
    monkeypatch.setattr("core.config.settings.settings.typesense.enabled", True)
    monkeypatch.setattr("v1.routers.explorer_search.SearchService.search_users", boom)
    monkeypatch.setattr(
        "v1.routers.explorer_search.PostgresConnectorDiscoveryRepository",
        FakeDiscovery,
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/explorers/search/users?q=karthik")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["hits"][0]["display_name"] == "Karthik Connector"
    assert body["hits"][0]["username"] == "karthikconnector"
