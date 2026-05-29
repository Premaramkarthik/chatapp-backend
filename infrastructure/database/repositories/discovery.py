"""Discovery snapshots and search outbox."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresDiscoveryRepository:
    """Postgres access for traveler_discovery_snapshots and search outbox."""

    async def get_snapshot(self, user_id: str) -> dict[str, Any] | None:
        """Return a snapshot row by user id."""
        result = await call_json_function(
            "fn_discovery_snapshots",
            2,
            {"user_id": user_id},
        )
        return row_from_jsonb(result)

    async def rebuild_snapshot(self, user_id: str) -> dict[str, Any] | None:
        """Rebuild denormalized discovery row from profile, trip, and privacy data."""
        result = await call_json_function(
            "fn_discovery_snapshots",
            1,
            {"user_id": user_id},
        )
        return row_from_jsonb(result)

    async def list_postgres_search(
        self,
        *,
        destination_country: str,
        current_country: str | None,
        viewer_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Fallback search on snapshots with block exclusion."""
        payload: dict[str, Any] = {
            "destination_country": destination_country,
            "viewer_id": viewer_id,
            "limit": limit,
            "offset": offset,
        }
        if current_country:
            payload["current_country"] = current_country
        result = await call_json_function("fn_discovery_snapshots", 3, payload)
        return list_from_jsonb(result)

    async def fetch_public_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        """Return discoverable snapshot rows for a set of user ids."""
        if not user_ids:
            return []
        result = await call_json_function(
            "fn_discovery_snapshots",
            4,
            {"user_ids": user_ids},
        )
        return list_from_jsonb(result)

    async def claim_outbox_batch(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Claim pending outbox rows for processing."""
        result = await call_json_function(
            "fn_search_outbox_events",
            1,
            {"limit": limit},
        )
        return list_from_jsonb(result)

    async def complete_outbox(self, event_id: str) -> None:
        """Mark an outbox event completed."""
        await call_json_function(
            "fn_search_outbox_events",
            2,
            {"event_id": event_id},
        )

    async def fail_outbox(self, event_id: str, error: str) -> None:
        """Mark an outbox event failed and reschedule with backoff."""
        await call_json_function(
            "fn_search_outbox_events",
            3,
            {"event_id": event_id, "error": error},
        )
