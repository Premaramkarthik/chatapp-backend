"""Build Tinode WebSocket login secrets for API clients."""

from __future__ import annotations

import base64
import json
from typing import Any

from core.config.settings import settings
from infrastructure.database.connection import call_json_function


class TinodeSessionNotReadyError(RuntimeError):
    """User has not completed Tinode link yet."""


async def build_tinode_session(*, user: dict[str, Any]) -> dict[str, Any]:
    """
    Return credentials for Tinode client login.

    Secret format matches ``rest_auth._principal_from_secret`` (base64 JSON).
    """
    mapping = await call_json_function("fn_tinode_user_mappings", 2, {"user_id": user["id"]})
    if not mapping or not mapping.get("tinode_user_id"):
        raise TinodeSessionNotReadyError("Tinode account not linked")

    payload = {
        "sub": user["keycloak_sub"],
        "keycloak_sub": user["keycloak_sub"],
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "name": user.get("display_name"),
    }
    secret = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return {
        "web_url": settings.tinode.web_url,
        "secret": secret,
        "user_id": user["id"],
        "tinode_user_id": mapping["tinode_user_id"],
        "expires_in": settings.tinode.auth_lifetime_sec,
    }
