"""Tests for chat conversation permissions and inbox status filter."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domains.chat.permissions import (
    assert_can_chat,
    conversation_permissions,
    enrich_inbox_row,
    enrich_mapping_row,
    is_provisioned_room_id,
    mapping_allows_chat,
)
from main import app
from v1.dependencies.auth import get_current_principal
from v1.schemas.principal import KeycloakPrincipal


def test_mapping_allows_chat_when_active_and_provisioned() -> None:
    assert mapping_allows_chat("active", "!room:local") is True


def test_mapping_allows_chat_false_when_provisioning() -> None:
    assert mapping_allows_chat("provisioning", "!pending:local") is False


def test_is_provisioned_room_id_rejects_pending() -> None:
    assert is_provisioned_room_id("!pending_abc:local") is False
    assert is_provisioned_room_id("!room:local") is True


def test_mapping_allows_chat_false_for_pending_active_status() -> None:
    assert mapping_allows_chat("active", "!pending_abc:local") is False


def test_can_archive_without_can_chat() -> None:
    perms = conversation_permissions(
        mapping_status="provisioning",
        can_chat=False,
        has_mapping=True,
        is_user_archived=False,
    )
    assert perms["can_archive"] is True
    assert perms["can_chat"] is False


def test_conversation_permissions_active() -> None:
    perms = conversation_permissions(
        mapping_status="active",
        can_chat=True,
        has_mapping=True,
    )
    assert perms["can_chat"] is True
    assert perms["is_archived"] is False
    assert perms["can_archive"] is True
    assert perms["can_reopen"] is False


def test_conversation_permissions_user_archived_still_chats() -> None:
    perms = conversation_permissions(
        mapping_status="active",
        can_chat=True,
        has_mapping=True,
        is_user_archived=True,
    )
    assert perms["can_chat"] is True
    assert perms["is_archived"] is True
    assert perms["can_archive"] is False
    assert perms["can_reopen"] is True


def test_assert_can_chat_raises_when_room_not_ready() -> None:
    perms = conversation_permissions(
        mapping_status="provisioning",
        can_chat=False,
        has_mapping=True,
    )
    with pytest.raises(ValueError, match="not active"):
        assert_can_chat(perms)


def test_enrich_inbox_row_passes_through_sql_can_chat() -> None:
    enriched = enrich_inbox_row(
        {
            "connection_id": str(uuid4()),
            "connection_status": "active",
            "can_chat": False,
            "is_user_archived": False,
            "mapping": {"status": "active"},
        },
    )
    assert enriched["status"] == "active"
    assert enriched["can_chat"] is False
    assert enriched["can_archive"] is True


def test_enrich_inbox_row_user_archived_flag() -> None:
    enriched = enrich_inbox_row(
        {
            "connection_id": str(uuid4()),
            "connection_status": "active",
            "can_chat": True,
            "is_user_archived": True,
            "mapping": {"status": "active"},
        },
    )
    assert enriched["is_archived"] is True
    assert enriched["can_reopen"] is True
    assert enriched["can_chat"] is True


def test_enrich_mapping_row_user_archived() -> None:
    enriched = enrich_mapping_row(
        {"id": str(uuid4()), "status": "active", "room_id": "!r:local"},
        is_user_archived=True,
    )
    assert enriched["can_reopen"] is True
    assert enriched["is_archived"] is True
    assert enriched["can_chat"] is True


def _message_sender_principal() -> KeycloakPrincipal:
    return KeycloakPrincipal(
        sub="chat-perms-sub",
        email="chat@example.com",
        email_verified=True,
        display_name="Chat User",
        preferred_username="chat@example.com",
        identity_provider="local",
        roles=["message:send", "message:create-room"],
    )


def test_inbox_status_query_passed_to_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("v1.middleware.authentication.settings.middleware.auth_enabled", False)
    app.dependency_overrides[get_current_principal] = _message_sender_principal
    captured: dict[str, str] = {}

    async def fake_user(*args: object, **kwargs: object) -> dict[str, str]:
        return {"id": str(uuid4()), "email": "chat@example.com"}

    class FakeRepo:
        async def list_inbox(self, user_id: str, *, inbox_status: str = "active") -> list[dict]:
            captured["user_id"] = user_id
            captured["inbox_status"] = inbox_status
            return []

    monkeypatch.setattr("v1.routers.chat._local_user", fake_user)
    monkeypatch.setattr(
        "v1.routers.chat.PostgresConversationRepository",
        FakeRepo,
    )

    with TestClient(app) as client:
        response = client.get("/v1/chat/inbox?status=archived")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert captured["inbox_status"] == "archived"


def test_business_event_returns_409_when_provisioning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("v1.middleware.authentication.settings.middleware.auth_enabled", False)
    app.dependency_overrides[get_current_principal] = _message_sender_principal
    conn_id = uuid4()

    async def fake_user(*args: object, **kwargs: object) -> dict[str, str]:
        return {"id": str(uuid4()), "email": "chat@example.com"}

    async def fake_require_active_connection(connection_id: str, user_id: str) -> dict:
        return {
            "id": connection_id,
            "user_a_id": user_id,
            "user_b_id": str(uuid4()),
            "status": "active",
        }

    class FakeRepo:
        async def get_by_connection(self, connection_id: str) -> dict:
            return {
                "id": str(uuid4()),
                "user_connection_id": connection_id,
                "room_id": "!pending:local",
                "status": "provisioning",
            }

    monkeypatch.setattr("v1.routers.chat._local_user", fake_user)
    monkeypatch.setattr(
        "v1.routers.chat._require_active_connection", fake_require_active_connection
    )
    monkeypatch.setattr("v1.routers.chat.PostgresConversationRepository", FakeRepo)

    async def fake_rate_limit(_: str) -> bool:
        return True

    monkeypatch.setattr("v1.routers.chat.matrix_rate_limiter.check_message_limit", fake_rate_limit)

    with TestClient(app) as client:
        response = client.post(
            f"/v1/chat/rooms/{conn_id}/events",
            json={"event_type": "connection", "payload": {}},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 409


def test_business_event_allows_user_archived_active_room(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("v1.middleware.authentication.settings.middleware.auth_enabled", False)
    app.dependency_overrides[get_current_principal] = _message_sender_principal
    conn_id = uuid4()

    async def fake_user(*args: object, **kwargs: object) -> dict[str, str]:
        return {"id": str(uuid4()), "email": "chat@example.com"}

    async def fake_require_active_connection(connection_id: str, user_id: str) -> dict:
        return {
            "id": connection_id,
            "user_a_id": user_id,
            "user_b_id": str(uuid4()),
            "status": "active",
        }

    class FakeRepo:
        async def get_by_connection(self, connection_id: str) -> dict:
            return {
                "id": str(uuid4()),
                "user_connection_id": connection_id,
                "room_id": "!room:local",
                "status": "active",
            }

    async def fake_publish(**kwargs: object) -> dict:
        return {"event_id": "evt-1"}

    monkeypatch.setattr("v1.routers.chat._local_user", fake_user)
    monkeypatch.setattr(
        "v1.routers.chat._require_active_connection", fake_require_active_connection
    )
    monkeypatch.setattr("v1.routers.chat.PostgresConversationRepository", FakeRepo)
    monkeypatch.setattr(
        "v1.routers.chat.matrix_business_event_service.publish",
        fake_publish,
    )

    async def fake_rate_limit(_: str) -> bool:
        return True

    monkeypatch.setattr("v1.routers.chat.matrix_rate_limiter.check_message_limit", fake_rate_limit)

    with TestClient(app) as client:
        response = client.post(
            f"/v1/chat/rooms/{conn_id}/events",
            json={"event_type": "connection", "payload": {}},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
