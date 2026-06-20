"""Connector profile route tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domains.users.user import User
from main import app
from v1.dependencies.auth import get_current_principal
from v1.schemas.principal import KeycloakPrincipal


def _connector_user() -> User:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return User(
        id=str(uuid4()),
        keycloak_sub="connector-sub",
        email="connector@example.com",
        display_name="Connector User",
        status="active",
        account_mode="connector",
        email_verified=True,
        created_via="email",
        created_at=now,
        updated_at=now,
    )


def _explorer_user() -> User:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return User(
        id=str(uuid4()),
        keycloak_sub="explorer-sub",
        email="explorer@example.com",
        display_name="Explorer User",
        status="active",
        account_mode="explorer",
        email_verified=True,
        created_via="email",
        created_at=now,
        updated_at=now,
    )


def _profile_row(user_id: str) -> dict:
    now = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    return {
        "user_id": user_id,
        "bio": "Helping travelers connect.",
        "home_country_id": None,
        "home_state_id": None,
        "home_city_id": None,
        "custom_home_country_name": None,
        "custom_home_state_name": None,
        "custom_home_city_name": None,
        "preferred_destination_countries": ["US", "JP"],
        "created_at": now,
        "updated_at": now,
    }


def test_get_connector_profile_returns_403_for_explorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explorer mode cannot read connector profile."""
    user = _explorer_user()

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = lambda: KeycloakPrincipal(
        sub=user.keycloak_sub,
        email=user.email,
        email_verified=True,
        display_name=user.display_name,
        preferred_username=user.email,
        identity_provider="email",
        roles=[],
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/connectors/profile")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "connector" in response.json()["detail"].lower()


def test_get_connector_profile_returns_404_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connector without profile row receives 404."""
    user = _connector_user()

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    class FakeConnectorRepository:
        async def get_connector_profile(self, user_id: str) -> dict | None:
            return None

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = lambda: KeycloakPrincipal(
        sub=user.keycloak_sub,
        email=user.email,
        email_verified=True,
        display_name=user.display_name,
        preferred_username=user.email,
        identity_provider="email",
        roles=[],
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    monkeypatch.setattr(
        "v1.routers.connectors.PostgresConnectorRepository", FakeConnectorRepository
    )
    try:
        with TestClient(app) as client:
            response = client.get("/v1/connectors/profile")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_get_connector_profile_returns_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connector with profile row receives profile payload."""
    user = _connector_user()
    row = _profile_row(user.id)

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    class FakeConnectorRepository:
        async def get_connector_profile(self, user_id: str) -> dict | None:
            assert user_id == user.id
            return row

    async def fake_enrich(_row: dict) -> dict:
        return {
            "display_home_country": None,
            "display_home_state": None,
            "display_home_city": None,
        }

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = lambda: KeycloakPrincipal(
        sub=user.keycloak_sub,
        email=user.email,
        email_verified=True,
        display_name=user.display_name,
        preferred_username=user.email,
        identity_provider="email",
        roles=[],
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    monkeypatch.setattr(
        "v1.routers.connectors.PostgresConnectorRepository", FakeConnectorRepository
    )
    monkeypatch.setattr("v1.routers.connectors.enrich_home_location", fake_enrich)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/connectors/profile")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["bio"] == "Helping travelers connect."
    assert body["preferred_destination_countries"] == ["US", "JP"]


def test_put_connector_profile_upserts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connector can upsert profile fields."""
    user = _connector_user()
    upsert_payload: dict | None = None

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    class FakeConnectorRepository:
        async def upsert_connector_profile(self, user_id: str, **fields: object) -> dict:
            nonlocal upsert_payload
            upsert_payload = {"user_id": user_id, **fields}
            return _profile_row(user_id) | {"bio": fields.get("bio", "Helping travelers connect.")}

    async def fake_enrich(_row: dict) -> dict:
        return {
            "display_home_country": None,
            "display_home_state": None,
            "display_home_city": None,
        }

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = lambda: KeycloakPrincipal(
        sub=user.keycloak_sub,
        email=user.email,
        email_verified=True,
        display_name=user.display_name,
        preferred_username=user.email,
        identity_provider="email",
        roles=[],
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    monkeypatch.setattr(
        "v1.routers.connectors.PostgresConnectorRepository", FakeConnectorRepository
    )
    monkeypatch.setattr("v1.routers.connectors.enrich_home_location", fake_enrich)
    try:
        with TestClient(app) as client:
            response = client.put(
                "/v1/connectors/profile",
                json={"bio": "Updated bio", "preferred_destination_countries": ["gb"]},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert upsert_payload is not None
    assert upsert_payload["bio"] == "Updated bio"
    assert upsert_payload["preferred_destination_countries"] == ["GB"]


def test_explorer_get_profile_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explorer mode cannot read explorer profile when account_mode is connector."""
    user = _connector_user()

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    monkeypatch.setattr(
        "v1.middleware.authentication.settings.middleware.auth_enabled",
        False,
    )
    app.dependency_overrides[get_current_principal] = lambda: KeycloakPrincipal(
        sub=user.keycloak_sub,
        email=user.email,
        email_verified=True,
        display_name=user.display_name,
        preferred_username=user.email,
        identity_provider="email",
        roles=[],
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/explorers/profile")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
