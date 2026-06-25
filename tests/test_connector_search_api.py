"""Connector search API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domains.users.user import User
from main import app
from v1.dependencies.auth import get_current_principal
from v1.schemas.connector_search import ExplorerSearchResponse, ExplorerSearchResult
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


def _principal(user: User, *, roles: list[str] | None = None) -> KeycloakPrincipal:
    return KeycloakPrincipal(
        sub=user.keycloak_sub,
        email=user.email,
        email_verified=True,
        display_name=user.display_name,
        preferred_username=user.email,
        identity_provider="email",
        roles=roles or ["trip:create", "trip:join", "message:send"],
    )


def test_connector_route_search_returns_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connector route search delegates to shared handler and returns hits."""
    user = _user(account_mode="connector")
    explorer_id = uuid4()

    async def fake_search(**kwargs: object) -> ExplorerSearchResponse:
        return ExplorerSearchResponse(
            hits=[
                ExplorerSearchResult(
                    user_id=explorer_id,
                    display_name="Explorer One",
                    headline="Open to connect",
                )
            ],
            total=1,
            limit=20,
            offset=0,
        )

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    monkeypatch.setattr("v1.routers.connector_search.search_explorers_by_route", fake_search)
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/connectors/search/explorers?destination_country=US")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["hits"][0]["display_name"] == "Explorer One"


def test_connector_explorer_route_search_uses_postgres_when_no_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connector route search uses Postgres when Typesense is on but no keyword."""
    user = _user(account_mode="connector")
    explorer_id = str(uuid4())

    class FakeDiscovery:
        async def list_discoverable_explorers(self, **kwargs: object) -> tuple[list[dict], int]:
            return (
                [
                    {
                        "user_id": explorer_id,
                        "display_name": "Explorer One",
                        "headline": "Open to connect",
                        "avatar_url": None,
                        "destination_country_iso": "US",
                        "destination_city_name": "Austin",
                        "current_country_iso": "US",
                        "languages": ["en"],
                        "interests": [],
                        "connection_availability": "open",
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
    monkeypatch.setattr("core.config.settings.settings.typesense.enabled", True)
    monkeypatch.setattr(
        "v1.routers.connector_search.PostgresDiscoveryRepository",
        FakeDiscovery,
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/connectors/search/explorers?destination_country=US")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["hits"][0]["display_name"] == "Explorer One"


def test_connector_explorer_route_search_uses_postgres_when_typesense_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connector route search uses Postgres when Typesense is disabled."""
    user = _user(account_mode="connector")
    explorer_id = str(uuid4())

    class FakeDiscovery:
        async def list_discoverable_explorers(self, **kwargs: object) -> tuple[list[dict], int]:
            return (
                [
                    {
                        "user_id": explorer_id,
                        "display_name": "Explorer Two",
                        "headline": "Visiting Japan",
                        "avatar_url": None,
                        "destination_country_iso": "JP",
                        "destination_city_name": "Tokyo",
                        "current_country_iso": "JP",
                        "languages": ["en", "ja"],
                        "interests": ["food"],
                        "connection_availability": "open",
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
    monkeypatch.setattr("core.config.settings.settings.typesense.enabled", False)
    monkeypatch.setattr(
        "v1.routers.connector_search.PostgresDiscoveryRepository",
        FakeDiscovery,
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/connectors/search/explorers?destination_country=JP")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["hits"][0]["display_name"] == "Explorer Two"


def test_connector_route_search_returns_503_on_typesense_error_with_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connector route search returns 503 when keyword Typesense search fails."""
    user = _user(account_mode="connector")

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    async def boom(self, filters: object, *, viewer_id: str | None = None) -> dict:
        raise TypesenseIntegrationError("connection refused")

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    monkeypatch.setattr("core.config.settings.settings.typesense.enabled", True)
    monkeypatch.setattr("v1.routers.connector_search.SearchService.search_travelers", boom)
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/connectors/search/explorers?destination_country=US&q=tokyo")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503


def test_search_service_sort_strings_within_typesense_limit() -> None:
    """Typesense allows at most three sort fields per query."""
    from domains.search.service import TRAVELER_SORT, USER_SORT

    assert len(USER_SORT.split(",")) <= 3
    assert len(TRAVELER_SORT.split(",")) <= 3


def test_connector_username_search_requires_min_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Username search rejects queries shorter than two characters."""
    user = _user(account_mode="connector")

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
            response = client.get("/v1/connectors/search/users?q=a")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_connector_username_search_falls_back_to_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connector username search uses postgres when Typesense fails."""
    user = _user(account_mode="connector")
    explorer_id = str(uuid4())

    class FakeDiscovery:
        async def search_by_username(self, **kwargs: object) -> tuple[list[dict], int]:
            return (
                [
                    {
                        "user_id": explorer_id,
                        "display_name": "Karthik Explorer",
                        "headline": "Visiting Tokyo",
                        "avatar_url": None,
                        "destination_country_iso": "JP",
                        "connection_availability": "open",
                        "home_country_iso": "IN",
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
    monkeypatch.setattr("v1.routers.connector_search.SearchService.search_users", boom)
    monkeypatch.setattr(
        "v1.routers.connector_search.PostgresDiscoveryRepository",
        FakeDiscovery,
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/connectors/search/users?q=karthik")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["hits"][0]["display_name"] == "Karthik Explorer"
    assert body["hits"][0]["username"] == "karthikexplorer"
