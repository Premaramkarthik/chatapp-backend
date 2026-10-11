"""Matrix attachment metadata persistence."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresMatrixAttachmentRepository:
    """Postgres access for Matrix attachment metadata."""

    async def upsert(
        self,
        *,
        room_id: str,
        event_id: str,
        mimetype: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        thumbnail_event_id: str | None = None,
        uploaded_by_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or update attachment metadata."""
        result = await call_json_function(
            "fn_matrix_attachment_metadata",
            1,
            {
                "room_id": room_id,
                "event_id": event_id,
                "mimetype": mimetype,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "thumbnail_event_id": thumbnail_event_id,
                "uploaded_by_user_id": uploaded_by_user_id,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(403, detail={"code": "matrix_attachment_owner_required"})
        return row

    async def list_for_room(self, room_id: str) -> list[dict[str, Any]]:
        """List attachment metadata for a room."""
        result = await call_json_function(
            "fn_matrix_attachment_metadata",
            2,
            {"room_id": room_id},
        )
        return list_from_jsonb(result)

    async def search(
        self,
        *,
        user_id: str,
        room_id: str | None = None,
        mimetype: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search attachment metadata."""
        result = await call_json_function(
            "fn_matrix_attachment_metadata",
            3,
            {"user_id": user_id, "room_id": room_id, "mimetype": mimetype},
        )
        return list_from_jsonb(result)

    async def record(
        self,
        *,
        room_id: str,
        event_id: str,
        mimetype: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        thumbnail_event_id: str | None = None,
        uploaded_by_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or update attachment metadata (router alias)."""
        return await self.upsert(
            room_id=room_id,
            event_id=event_id,
            mimetype=mimetype,
            size_bytes=size_bytes,
            sha256=sha256,
            thumbnail_event_id=thumbnail_event_id,
            uploaded_by_user_id=uploaded_by_user_id,
        )
