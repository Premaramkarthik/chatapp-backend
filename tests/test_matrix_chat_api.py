"""Matrix chat API and provisioning unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domains.matrix.provisioning.service import (
    MatrixProvisionError,
    MatrixProvisioningService,
    matrix_localpart_for_user,
    matrix_mxid_for_localpart,
)
from domains.matrix.rooms.service import MatrixRoomProvisionError, MatrixRoomService
from domains.matrix.session.service import MatrixSessionNotReadyError, MatrixSessionService
from main import app
from v1.dependencies.auth import get_current_auth_session, get_current_principal
from v1.schemas.principal import KeycloakPrincipal


def test_matrix_localpart_and_mxid() -> None:
    user_id = "550e8400-e29b-41d4-a716-446655440000"
    localpart = matrix_localpart_for_user(user_id)
    assert localpart == "u550e8400e29b41d4a716446655440000"
    assert matrix_mxid_for_localpart(localpart).startswith("@")


@pytest.mark.asyncio
async def test_matrix_session_not_ready_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("domains.matrix.session.service.settings.matrix.enabled", False)
    service = MatrixSessionService()
    with pytest.raises(MatrixSessionNotReadyError, match="disabled"):
        await service.create_session(user={"id": "u1", "email": "a@b.com"})


@pytest.mark.asyncio
async def test_matrix_session_requires_bff_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("domains.matrix.session.service.settings.matrix.enabled", True)
    with pytest.raises(MatrixSessionNotReadyError, match="matrix_login_required"):
        await MatrixSessionService().create_session(user={"id": "u1"})


@pytest.mark.asyncio
async def test_matrix_provision_requires_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("domains.matrix.provisioning.service.settings.matrix.enabled", False)
    with pytest.raises(MatrixProvisionError):
        await MatrixProvisioningService().ensure_user_provisioned(user_id="u1")


@pytest.mark.asyncio
async def test_matrix_room_provision_fails_without_mappings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = {"id": "c1", "user_a_id": "a", "user_b_id": "b"}

    class FakeConversations:
        async def provision_for_connection(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "id": "m1",
                "user_connection_id": kwargs["connection_id"],
                "room_id": "!pending_c1:local",
                "status": "provisioning",
            }

        async def update_mapping(self, **kwargs: Any) -> dict[str, Any]:
            return {"id": "m1", **kwargs}

    class FakeProvisioning:
        async def ensure_user_provisioned(self, **kwargs: Any) -> dict[str, Any]:
            return {"mxid": "@u:matrix.local"}

    class FakeUsers:
        async def get_by_user_id(self, user_id: str) -> dict[str, Any] | None:
            return None

    monkeypatch.setattr("domains.matrix.rooms.service.settings.matrix.enabled", True)
    monkeypatch.setattr(
        "domains.matrix.rooms.service.PostgresConversationRepository",
        lambda: FakeConversations(),
    )
    monkeypatch.setattr(
        "domains.matrix.rooms.service.MatrixProvisioningService",
        lambda *args, **kwargs: FakeProvisioning(),
    )
    monkeypatch.setattr(
        "domains.matrix.rooms.service.PostgresMatrixUserRepository",
        lambda: FakeUsers(),
    )

    async def fake_call(function_name: str, mode: int, payload: dict[str, Any]) -> Any:
        if function_name == "fn_users" and mode == 2:
            return {"display_name": "Peer"}
        raise AssertionError((function_name, mode))

    monkeypatch.setattr("domains.matrix.rooms.service.call_json_function", fake_call)

    with pytest.raises(MatrixRoomProvisionError):
        await MatrixRoomService().provision_dm_for_connection(
            connection=conn,
            created_by_user_id="a",
        )


def _message_sender_principal() -> KeycloakPrincipal:
    return KeycloakPrincipal(
        sub="matrix-sub",
        email="matrix@example.com",
        email_verified=True,
        display_name="Matrix User",
        preferred_username="matrix@example.com",
        identity_provider="local",
        roles=["message:send", "message:create-room"],
    )


def test_matrix_search_attachments_route_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("v1.middleware.authentication.settings.middleware.auth_enabled", False)
    app.dependency_overrides[get_current_principal] = _message_sender_principal

    async def fake_user(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"id": str(uuid4()), "email": "matrix@example.com"}

    async def fake_search(**kwargs: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr("v1.routers.chat._local_user", fake_user)
    monkeypatch.setattr("v1.routers.chat.matrix_search_service.search_attachments", fake_search)

    with TestClient(app) as client:
        response = client.get("/v1/chat/search/attachments")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_matrix_session_route_conflict_when_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("v1.middleware.authentication.settings.middleware.auth_enabled", False)
    app.dependency_overrides[get_current_principal] = _message_sender_principal

    async def fake_user(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"id": str(uuid4()), "email": "matrix@example.com"}

    async def fake_session(**kwargs: Any) -> dict[str, Any]:
        raise MatrixSessionNotReadyError("Matrix account not linked")

    monkeypatch.setattr("v1.routers.chat._local_user", fake_user)
    monkeypatch.setattr("v1.routers.chat.matrix_session_service.create_session", fake_session)
    app.dependency_overrides[get_current_auth_session] = lambda: SimpleNamespace(id=str(uuid4()))

    with TestClient(app) as client:
        response = client.get("/v1/chat/matrix/session")

    app.dependency_overrides.clear()
    assert response.status_code == 409
