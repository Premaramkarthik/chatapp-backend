"""Matrix room mapping and settings persistence."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import row_from_jsonb


class PostgresMatrixRoomRepository:
    """Postgres access for Matrix room mappings and settings."""

    async def get_settings(self, room_id: str) -> dict[str, Any] | None:
        """Return room settings for a Matrix room."""
        result = await call_json_function(
            "fn_matrix_room_settings",
            2,
            {"room_id": room_id},
        )
        return row_from_jsonb(result)

    async def upsert_settings(
        self,
        *,
        room_id: str,
        pinned_event_ids: list[str] | None = None,
        muted: bool | None = None,
        retention_policy: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or patch room settings."""
        payload: dict[str, Any] = {"room_id": room_id}
        if pinned_event_ids is not None:
            payload["pinned_event_ids"] = pinned_event_ids
        if muted is not None:
            payload["muted"] = muted
        if retention_policy is not None:
            payload["retention_policy"] = retention_policy
        if metadata is not None:
            payload["metadata"] = metadata
        result = await call_json_function("fn_matrix_room_settings", 1, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_room_settings mode 1 returned no row")
        return row

    async def upsert_room_settings(
        self,
        *,
        room_id: str,
        pinned_event_ids: list[str] | None = None,
        muted: bool | None = None,
        retention_policy: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or patch room settings (router alias)."""
        return await self.upsert_settings(
            room_id=room_id,
            pinned_event_ids=pinned_event_ids,
            muted=muted,
            retention_policy=retention_policy,
            metadata=metadata,
        )
