"""Connection screen API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
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


def _principal(user: User, *, roles: list[str]) -> KeycloakPrincipal:
    return KeycloakPrincipal(
        sub=user.keycloak_sub,
        email=user.email,
        email_verified=True,
        display_name=user.display_name,
        preferred_username=user.email,
        identity_provider="email",
        roles=roles,
    )


def _peer(user_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "display_name": "Alex Explorer",
        "account_mode": "explorer",
        "avatar_url": None,
        "headline": "Crossing borders",
        "home_label": "London, GB",
        "destination_country_iso": "US",
        "destination_city_name": "New York",
        "languages": ["en"],
        "last_active_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
    }


@pytest.fixture
def connector_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    user = _user(account_mode="connector")

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    monkeypatch.setattr("v1.middleware.authentication.settings.middleware.auth_enabled", False)
    app.dependency_overrides[get_current_principal] = lambda: _principal(
        user,
        roles=["trip:join", "message:send"],
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def explorer_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    user = _user(account_mode="explorer")

    class FakeUserRepository:
        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            return user

    monkeypatch.setattr("v1.middleware.authentication.settings.middleware.auth_enabled", False)
    app.dependency_overrides[get_current_principal] = lambda: _principal(
        user,
        roles=["trip:create", "message:send"],
    )
    monkeypatch.setattr("v1.dependencies.account_mode.PostgresUserRepository", FakeUserRepository)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_connector_connections_screen_summary(
    connector_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_summary(_self, viewer_id: str) -> dict[str, int]:
        assert viewer_id
        return {
            "incoming_pending": 2,
            "sent_pending": 1,
            "active": 3,
            "history_count": 4,
        }

    monkeypatch.setattr(
        "v1.routers.connections.ConnectionScreenRepository.summary",
        fake_summary,
    )
    response = connector_client.get("/v1/connections/screens/summary")
    assert response.status_code == 200
    assert response.json() == {
        "incoming_pending": 2,
        "sent_pending": 1,
        "active": 3,
        "history_count": 4,
    }


def test_explorer_connections_screen_summary(
    explorer_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_summary(_self, viewer_id: str) -> dict[str, int]:
        return {
            "incoming_pending": 1,
            "sent_pending": 0,
            "active": 2,
            "history_count": 1,
        }

    monkeypatch.setattr(
        "v1.routers.explorer_connections.ConnectionScreenRepository.summary",
        fake_summary,
    )
    response = explorer_client.get("/v1/explorers/connections/screens/summary")
    assert response.status_code == 200
    assert response.json()["incoming_pending"] == 1


def test_connector_connections_screen_incoming_enriched(
    connector_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = str(uuid4())
    peer_id = str(uuid4())

    async def fake_incoming(_self, viewer_id: str) -> list[dict[str, Any]]:
        return [
            {
                "request_id": request_id,
                "message": "Hello",
                "status": "pending",
                "created_at": datetime(2026, 1, 2, tzinfo=UTC),
                "expires_at": None,
                "peer": _peer(peer_id),
            }
        ]

    monkeypatch.setattr(
        "v1.routers.connections.ConnectionScreenRepository.list_incoming",
        fake_incoming,
    )
    response = connector_client.get("/v1/connections/screens/incoming")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["peer"]["destination_country_iso"] == "US"


def test_explorer_gets_403_on_connector_screen_routes(
    explorer_client: TestClient,
) -> None:
    response = explorer_client.get("/v1/connections/screens/summary")
    assert response.status_code == 403


def test_connector_gets_403_on_explorer_screen_routes(
    connector_client: TestClient,
) -> None:
    response = connector_client.get("/v1/explorers/connections/screens/summary")
    assert response.status_code == 403


def test_connector_connections_screen_active_and_history(
    connector_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = str(uuid4())
    peer_id = str(uuid4())

    async def fake_active(_self, viewer_id: str) -> list[dict[str, Any]]:
        return [
            {
                "connection_id": connection_id,
                "connected_at": datetime(2026, 1, 3, tzinfo=UTC),
                "peer": _peer(peer_id),
                "can_chat": True,
                "conversation_status": "active",
            }
        ]

    async def fake_history(_self, viewer_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "kind": "request_rejected",
                "occurred_at": datetime(2026, 1, 4, tzinfo=UTC),
                "message": "No thanks",
                "request_id": str(uuid4()),
                "connection_id": None,
                "peer": _peer(peer_id),
            }
        ]

    monkeypatch.setattr(
        "v1.routers.connections.ConnectionScreenRepository.list_active",
        fake_active,
    )
    monkeypatch.setattr(
        "v1.routers.connections.ConnectionScreenRepository.list_history",
        fake_history,
    )

    active = connector_client.get("/v1/connections/screens/active")
    assert active.status_code == 200
    assert active.json()["items"][0]["can_chat"] is True

    history = connector_client.get("/v1/connections/screens/history?limit=10")
    assert history.status_code == 200
    assert history.json()["items"][0]["kind"] == "request_rejected"
