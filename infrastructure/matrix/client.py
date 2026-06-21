"""matrix-nio helpers for rooms, search, and custom events."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import httpx

from core.config.settings import settings
from core.logging.logger import get_logger, log_warning
from core.observability.prometheus_metrics import (
    MATRIX_CLIENT_DURATION_SECONDS,
    MATRIX_CLIENT_REQUESTS_TOTAL,
)
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
        body["name"] = room_alias

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
            )
            if response.status_code not in {200, 201}:
                MATRIX_CLIENT_REQUESTS_TOTAL.labels(operation="room_create", status="failed").inc()
                raise MatrixIntegrationError(
                    "Matrix room creation failed",
                    context={"status_code": response.status_code, "body": response.text[:200]},
                )
            payload = response.json()
            room_id = payload.get("room_id")
            if not room_id:
                raise MatrixIntegrationError("Matrix room creation failed: missing room_id")
            MATRIX_CLIENT_REQUESTS_TOTAL.labels(operation="room_create", status="success").inc()
            return str(room_id)
    except MatrixIntegrationError:
        raise
    except Exception as exc:
        MATRIX_CLIENT_REQUESTS_TOTAL.labels(operation="room_create", status="error").inc()
        raise MatrixIntegrationError("Matrix room creation failed") from exc
    finally:
        duration = time.perf_counter() - started
        MATRIX_CLIENT_DURATION_SECONDS.labels(operation="room_create").observe(duration)


async def send_room_event(
    *,
    access_token: str,
    sender_mxid: str,
    room_id: str,
    event_type: str,
    content: dict[str, Any],
) -> str:
    """Send a custom room event and return the event id."""
    txn_id = hashlib.sha256(
        json.dumps(
            {"room_id": room_id, "event_type": event_type, "content": content},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    url = (
        f"{settings.matrix.homeserver_url.rstrip('/')}/_matrix/client/v3/rooms/"
        f"{room_id}/send/{event_type}/{txn_id}"
    )
    try:
        async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
            response = await client.put(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=content,
            )
            if response.status_code not in {200, 201}:
                MATRIX_CLIENT_REQUESTS_TOTAL.labels(operation="room_send", status="failed").inc()
                raise MatrixIntegrationError(
                    "Matrix event publish failed",
                    context={"room_id": room_id, "event_type": event_type},
                )
            payload = response.json()
            event_id = payload.get("event_id")
            if not event_id:
                raise MatrixIntegrationError("Matrix event publish failed: missing event_id")
            MATRIX_CLIENT_REQUESTS_TOTAL.labels(operation="room_send", status="success").inc()
            return str(event_id)
    except MatrixIntegrationError:
        raise
    except Exception as exc:
        MATRIX_CLIENT_REQUESTS_TOTAL.labels(operation="room_send", status="error").inc()
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
