"""Tinode REST authenticator integration."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from core.config.settings import settings
from core.observability.prometheus_metrics import (
    TINODE_REST_AUTH_DURATION_SECONDS,
    TINODE_REST_AUTH_TOTAL,
)
from infrastructure.database.connection import call_json_function
from v1.utils.base import TinodeAuthError


def verify_shared_secret(header_secret: str | None, query_secret: str | None) -> None:
    """Protect the internal Tinode REST auth endpoint."""
    expected = settings.tinode.rest_auth_secret_value
    supplied = header_secret or query_secret
    if expected and supplied != expected:
        raise TinodeAuthError("Invalid Tinode secret")


async def handle_tinode_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle Tinode REST authenticator endpoint payloads."""
    started = time.perf_counter()
    endpoint = payload.get("endpoint") or "auth"
    if endpoint == "rtagns":
        return {"strarr": ["email", "tel", "keycloak"]}
    if endpoint == "checkunique":
        return {"boolval": True}
    try:
        if endpoint == "auth":
            return await _handle_auth(payload)
        if endpoint == "link":
            return await _handle_link(payload)
        if endpoint in {"add", "upd", "del", "gen"}:
            return {"err": "unsupported"}
        return {"err": "unsupported"}
    finally:
        duration = time.perf_counter() - started
        TINODE_REST_AUTH_TOTAL.labels(endpoint=endpoint).inc()
        TINODE_REST_AUTH_DURATION_SECONDS.labels(endpoint=endpoint).observe(duration)


async def _handle_auth(payload: dict[str, Any]) -> dict[str, Any]:
    principal = _principal_from_secret(payload.get("secret"))
    user = await call_json_function("fn_users", 1, principal)
    mapping = await call_json_function("fn_tinode_user_mappings", 2, {"user_id": user["id"]})

    tags = _tags_for_user(user)
    rec: dict[str, Any] = {
        "authlvl": "auth",
        "state": "ok",
        "lifetime": f"{settings.tinode.auth_lifetime_sec}s",
        "features": 1,
        "tags": tags,
    }
    if mapping and mapping.get("tinode_user_id"):
        rec["uid"] = mapping["tinode_user_id"]
        return {"rec": rec}

    return {
        "rec": rec,
        "newacc": {
            "auth": "JRWPS",
            "anon": "N",
            "public": {
                "fn": user.get("display_name") or user.get("email") or "PariPath User",
            },
            "trusted": {
                "paripath_user_id": user["id"],
                "keycloak_sub": user["keycloak_sub"],
            },
            "private": {},
        },
    }


async def _handle_link(payload: dict[str, Any]) -> dict[str, Any]:
    principal = _principal_from_secret(payload.get("secret"))
    rec = payload.get("rec") or {}
    tinode_user_id = rec.get("uid")
    if not tinode_user_id:
        return {"err": "malformed"}

    user = await call_json_function("fn_users", 1, principal)
    mapping = await call_json_function(
        "fn_tinode_user_mappings",
        1,
        {"user_id": user["id"], "tinode_user_id": tinode_user_id},
    )
    return {
        "rec": {
            "uid": mapping["tinode_user_id"],
            "authlvl": "auth",
            "state": "ok",
            "lifetime": f"{settings.tinode.auth_lifetime_sec}s",
            "features": 1,
            "tags": _tags_for_user(user),
        }
    }


def _principal_from_secret(secret: str | None) -> dict[str, Any]:
    if not secret:
        raise TinodeAuthError("missing secret")

    decoded = _decode_secret(secret)
    try:
        data = json.loads(decoded)
    except json.JSONDecodeError:
        if not settings.tinode.allow_plaintext_dev_secret:
            raise TinodeAuthError("secret is not JSON") from None
        data = {"keycloak_sub": decoded}

    keycloak_sub = data.get("keycloak_sub") or data.get("sub")
    if not keycloak_sub:
        raise TinodeAuthError("secret missing keycloak subject")
    return {
        "keycloak_sub": str(keycloak_sub),
        "email": data.get("email"),
        "display_name": (
            data.get("display_name") or data.get("name") or data.get("preferred_username")
        ),
    }


def _decode_secret(secret: str) -> str:
    try:
        return base64.b64decode(secret, validate=True).decode("utf-8")
    except Exception:
        if settings.tinode.allow_plaintext_dev_secret:
            return secret
        raise TinodeAuthError("secret is not base64") from None


def _tags_for_user(user: dict[str, Any]) -> list[str]:
    tags = [f"keycloak:{user['keycloak_sub']}", f"paripath:{user['id']}"]
    if user.get("email"):
        tags.append(f"email:{user['email']}")
    return tags
