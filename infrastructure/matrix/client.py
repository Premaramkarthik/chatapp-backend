"""matrix-nio helpers for rooms, search, and custom events."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from core.config.settings import settings
from core.logging.logger import get_logger, log_warning
from v1.utils.base import MatrixIntegrationError

logger = get_logger(__name__)


async def create_direct_encrypted_room(
    *,
    access_token: str,
    creator_mxid: str,
    invite_mxid: str,
    room_alias: str | None = None,
) -> str:
    """Create an E2EE-enabled direct room and return the room id."""
    url = f"{settings.matrix.homeserver_url.rstrip('/')}/_matrix/client/v3/createRoom"
    body: dict[str, Any] = {
        "preset": "trusted_private_chat",
        "is_direct": True,
        "invite": [invite_mxid],
        "initial_state": [
            {
                "type": "m.room.encryption",
                "state_key": "",
                "content": {"algorithm": "m.megolm.v1.aes-sha2"},
            }
        ],
    }
    if room_alias:
        body["room_alias_name"] = room_alias.removeprefix("#").split(":", 1)[0]
        body["visibility"] = "private"

    time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
            )
            if response.status_code not in {200, 201}:
                raise MatrixIntegrationError(
                    "Matrix room creation failed",
                    context={"status_code": response.status_code},
                )
            payload = response.json()
            room_id = payload.get("room_id")
            if not room_id:
                raise MatrixIntegrationError("Matrix room creation failed: missing room_id")
            return str(room_id)
    except MatrixIntegrationError:
        raise
    except Exception as exc:
        raise MatrixIntegrationError("Matrix room creation failed") from exc


async def send_room_event(
    *,
    access_token: str,
    sender_mxid: str,
    room_id: str,
    event_type: str,
    content: dict[str, Any],
    transaction_id: str | None = None,
) -> str:
    """Send a custom room event and return the event id."""
    if event_type != "m.room.encrypted":
        raise MatrixIntegrationError("Server plaintext room events are retired")
    txn_id = transaction_id or uuid4().hex
    url = (
        f"{settings.matrix.homeserver_url.rstrip('/')}/_matrix/client/v3/rooms/"
        f"{quote(room_id, safe='')}/send/{quote(event_type, safe='')}/{quote(txn_id, safe='')}"
    )
    try:
        async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
            response = await client.put(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=content,
            )
            if response.status_code not in {200, 201}:
                raise MatrixIntegrationError(
                    "Matrix event publish failed",
                    context={"room_id": room_id, "event_type": event_type},
                )
            payload = response.json()
            event_id = payload.get("event_id")
            if not event_id:
                raise MatrixIntegrationError("Matrix event publish failed: missing event_id")
            return str(event_id)
    except MatrixIntegrationError:
        raise
    except Exception as exc:
        raise MatrixIntegrationError("Matrix event publish failed") from exc


async def search_messages(
    *,
    access_token: str,
    mxid: str,
    search_term: str,
    room_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Proxy Synapse message search for the authenticated user."""
    url = f"{settings.matrix.homeserver_url.rstrip('/')}/_matrix/client/v3/search"
    body: dict[str, Any] = {
        "search_categories": {
            "room_events": {
                "search_term": search_term,
                "filter": {"limit": limit},
                "order_by": "recent",
            }
        }
    }
    if room_id:
        body["search_categories"]["room_events"]["filter"]["rooms"] = [room_id]
    async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as http:
        response = await http.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
        )
        if response.status_code != 200:
            log_warning(
                logger,
                "Matrix message search failed",
                matrix_category="search",
                status_code=response.status_code,
                mxid=mxid,
            )
            raise MatrixIntegrationError(
                "Matrix search failed",
                context={"status_code": response.status_code},
            )
    payload = response.json()
    results = payload.get("search_categories", {}).get("room_events", {}).get("results", [])
    return [item.get("result", item) for item in results if isinstance(item, dict)]


def payload_hash(payload: dict[str, Any]) -> str:
    """Return a stable hash for business event deduplication."""
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def reconcile_encrypted_room(
    *, access_token: str, room_alias: str, expected_members: set[str]
) -> str | None:
    """Adopt an existing deterministic alias only after verifying its encryption and members."""
    base = settings.matrix.homeserver_url.rstrip("/") + "/_matrix/client/v3"
    async with httpx.AsyncClient(
        timeout=settings.http.timeout_seconds, headers={"Authorization": f"Bearer {access_token}"}
    ) as http:
        response = await http.get(f'{base}/directory/room/{quote(room_alias, safe="")}')
        if response.status_code == 404:
            return None
        response.raise_for_status()
        room_id = response.json()["room_id"]
        state = await http.get(f'{base}/rooms/{quote(room_id, safe="")}/state')
        state.raise_for_status()
        events = state.json()
        encryption = next(
            (e["content"].get("algorithm") for e in events if e["type"] == "m.room.encryption"),
            None,
        )
        members = {
            e["state_key"]: e["content"].get("membership")
            for e in events
            if e["type"] == "m.room.member" and e["content"].get("membership") in {"join", "invite"}
        }
        if encryption != "m.megolm.v1.aes-sha2" or set(members) != expected_members:
            raise MatrixIntegrationError(
                "Existing room does not match authorized participants and encryption"
            )
        return room_id
