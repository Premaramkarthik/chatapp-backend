"""Tinode REST auth tests."""

import base64
import json
from typing import Any

import pytest

from infrastructure.tinode import rest_auth as tinode_auth


@pytest.mark.asyncio
async def test_tinode_auth_returns_new_account(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(function_name: str, mode: int, payload: dict[str, Any]) -> dict | None:
        if function_name == "fn_users" and mode == 1:
            return {
                "id": "f5e3b0b8-9c19-4e0d-a669-0b9b1d5fd55f",
                "keycloak_sub": payload["keycloak_sub"],
                "email": payload.get("email"),
                "display_name": payload.get("display_name"),
                "status": "active",
            }
        if function_name == "fn_tinode_user_mappings" and mode == 2:
            return None
        raise AssertionError((function_name, mode, payload))

    monkeypatch.setattr(tinode_auth, "call_json_function", fake_call)
    secret = base64.b64encode(
        json.dumps(
            {
                "sub": "kc-user-1",
                "email": "user@example.com",
                "name": "Example User",
            }
        ).encode("utf-8")
    ).decode("utf-8")

    response = await tinode_auth.handle_tinode_request({"endpoint": "auth", "secret": secret})

    assert response["rec"]["authlvl"] == "auth"
    assert response["newacc"]["trusted"]["keycloak_sub"] == "kc-user-1"
