"""Chat API and provisioning unit tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from domains.chat.provision import ProvisionError, provision_conversation_for_connection
from domains.chat.session import TinodeSessionNotReadyError, build_tinode_session
from infrastructure.tinode.grpc_client import P2pProvisionResult
from infrastructure.tinode.p2p_topic import P2pTopicNames


@pytest.mark.asyncio
async def test_build_tinode_session_requires_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(function_name: str, mode: int, payload: dict[str, Any]) -> Any:
        if function_name == "fn_tinode_user_mappings" and mode == 2:
            return None
        raise AssertionError((function_name, mode))

    monkeypatch.setattr("domains.chat.session.call_json_function", fake_call)
    with pytest.raises(TinodeSessionNotReadyError):
        await build_tinode_session(
            user={"id": "u1", "keycloak_sub": "kc-1", "email": "a@b.com"},
        )


@pytest.mark.asyncio
async def test_build_tinode_session_returns_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(function_name: str, mode: int, payload: dict[str, Any]) -> Any:
        if function_name == "fn_tinode_user_mappings" and mode == 2:
            return {"tinode_user_id": "usrAAAAAAAAAAA"}
        raise AssertionError((function_name, mode))

    monkeypatch.setattr("domains.chat.session.call_json_function", fake_call)
    out = await build_tinode_session(
        user={"id": "u1", "keycloak_sub": "kc-1", "email": "a@b.com", "display_name": "A"},
    )
    assert out["tinode_user_id"] == "usrAAAAAAAAAAA"
    assert out["secret"]
    assert "web_url" in out


@pytest.mark.asyncio
async def test_provision_fails_without_tinode_mappings(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = {"id": "c1", "user_a_id": "a", "user_b_id": "b"}

    class FakeRepo:
        async def provision_for_connection(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "id": "m1",
                "user_connection_id": kwargs["connection_id"],
                "tinode_topic_id": "pp_conn_c1",
                "status": "provisioning",
                "created_at": "2020-01-01T00:00:00Z",
            }

        async def update_mapping(self, **kwargs: Any) -> dict[str, Any]:
            return {**kwargs, "id": "m1", "user_connection_id": conn["id"]}

    async def fake_call(function_name: str, mode: int, payload: dict[str, Any]) -> Any:
        if function_name == "fn_tinode_user_mappings":
            return None
        if function_name == "fn_users" and mode == 2:
            return {"display_name": "Peer"}
        raise AssertionError((function_name, mode))

    monkeypatch.setattr(
        "domains.chat.provision.PostgresConversationRepository",
        lambda: FakeRepo(),
    )
    monkeypatch.setattr("domains.chat.provision.call_json_function", fake_call)

    with pytest.raises(ProvisionError):
        await provision_conversation_for_connection(
            connection=conn,
            created_by_user_id="a",
        )


@pytest.mark.asyncio
async def test_provision_activates_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = {"id": "c1", "user_a_id": "a", "user_b_id": "b"}
    names = P2pTopicNames(
        internal_topic_id="p2pABC",
        topic_for_user_a="usrB",
        topic_for_user_b="usrA",
    )
    result = P2pProvisionResult(names=names, grpc_reachable=True, trusted_public={})
    updated: dict[str, Any] = {}

    class FakeRepo:
        async def provision_for_connection(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "id": "m1",
                "user_connection_id": kwargs["connection_id"],
                "tinode_topic_id": "pp_conn_c1",
                "status": "provisioning",
                "created_at": "2020-01-01T00:00:00Z",
            }

        async def update_mapping(self, **kwargs: Any) -> dict[str, Any]:
            updated.update(kwargs)
            return {
                "id": "m1",
                "user_connection_id": conn["id"],
                "tinode_topic_id": kwargs["tinode_topic_id"],
                "tinode_topic_name": kwargs["tinode_topic_name"],
                "status": kwargs["status"],
                "created_at": "2020-01-01T00:00:00Z",
            }

    async def fake_call(function_name: str, mode: int, payload: dict[str, Any]) -> Any:
        if function_name == "fn_tinode_user_mappings" and mode == 2:
            uid = payload["user_id"]
            return {"tinode_user_id": "usrA" if uid == "a" else "usrB"}
        if function_name == "fn_users" and mode == 2:
            return {"display_name": "Peer"}
        raise AssertionError((function_name, mode))

    monkeypatch.setattr(
        "domains.chat.provision.PostgresConversationRepository",
        lambda: FakeRepo(),
    )
    monkeypatch.setattr("domains.chat.provision.call_json_function", fake_call)
    monkeypatch.setattr(
        "domains.chat.provision.prepare_p2p_conversation",
        AsyncMock(return_value=result),
    )

    row = await provision_conversation_for_connection(
        connection=conn,
        created_by_user_id="a",
    )
    assert row["status"] == "active"
    assert updated["tinode_topic_id"] == "p2pABC"
    assert updated["tinode_topic_name"] == "usrB"
