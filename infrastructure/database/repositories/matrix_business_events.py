"""Matrix business event persistence."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresMatrixBusinessEventRepository:
    """Postgres access for Matrix business events."""

    async def record(
        self,
        *,
        room_id: str,
        event_id: str,
        event_type: str,
        payload_hash: str,
        aggregate_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a published business event."""
        result = await call_json_function(
            "fn_matrix_business_events",
            1,
            {
                "room_id": room_id,
                "event_id": event_id,
                "event_type": event_type,
                "payload_hash": payload_hash,
                "aggregate_id": aggregate_id,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_business_events mode 1 returned no row")
        return row

    async def list_for_room(self, room_id: str) -> list[dict[str, Any]]:
        """List business events for a room."""
        result = await call_json_function(
            "fn_matrix_business_events",
            2,
            {"room_id": room_id},
        )
        return list_from_jsonb(result)
