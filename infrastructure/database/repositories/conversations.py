"""Conversation mapping persistence (Matrix-backed)."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function, fetchrow
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresConversationRepository:
    """Postgres access for Matrix room mappings per connection."""

    async def get_by_connection(self, connection_id: str) -> dict[str, Any] | None:
        """Return mapping for a user connection."""
        result = await call_json_function(
            "fn_matrix_room_mappings",
            1,
            {"user_connection_id": connection_id},
        )
        return row_from_jsonb(result)

    async def provision_for_connection(
        self,
        *,
        connection_id: str,
        created_by_user_id: str,
    ) -> dict[str, Any]:
        """Create or return a conversation mapping for a connection."""
        result = await call_json_function(
            "fn_matrix_room_mappings",
            2,
            {
                "user_connection_id": connection_id,
                "created_by_user_id": created_by_user_id,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_room_mappings mode 2 returned no row")
        return row

    async def list_inbox(
        self,
        user_id: str,
        *,
        inbox_status: str = "active",
    ) -> list[dict[str, Any]]:
        """List active connections with peer and mapping metadata."""
        result = await call_json_function(
            "fn_matrix_room_mappings",
            3,
            {"user_id": user_id, "status": inbox_status},
        )
        return list_from_jsonb(result)

    async def update_mapping(
        self,
        *,
        connection_id: str,
        room_id: str | None = None,
        room_alias: str | None = None,
        status: str | None = None,
        business_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update room fields or provisioning status."""
        payload: dict[str, Any] = {"user_connection_id": connection_id}
        if room_id is not None:
            payload["room_id"] = room_id
        if room_alias is not None:
            payload["room_alias"] = room_alias
        if status is not None:
            payload["status"] = status
        if business_context is not None:
            payload["business_context"] = business_context
        result = await call_json_function("fn_matrix_room_mappings", 4, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_room_mappings mode 4 returned no row")
        return row

    async def is_user_archived(self, user_id: str, connection_id: str) -> bool:
        """Return whether the viewer has archived this connection in their inbox."""
        result = await fetchrow(
            """
            SELECT EXISTS (
                SELECT 1 FROM matrix_inbox_archive
                WHERE user_id = $1::uuid
                  AND user_connection_id = $2::uuid
            ) AS archived
            """,
            user_id,
            connection_id,
        )
        return bool(result["archived"]) if result else False

    async def archive_for_connection(
        self,
        connection_id: str,
        *,
        user_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Mark connection archived in the viewer's inbox."""
        result = await call_json_function(
            "fn_matrix_room_mappings",
            5,
            {
                "user_connection_id": connection_id,
                "user_id": user_id,
                "reason": reason,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_room_mappings mode 5 returned no row")
        return row

    async def archive_between_users(self, user_id: str, other_user_id: str) -> None:
        """Archive conversation in the blocker's inbox when users share an active connection."""
        from infrastructure.database.repositories.matching import PostgresMatchingRepository

        conn = await PostgresMatchingRepository().get_connection_between(user_id, other_user_id)
        if conn is None:
            return
        try:
            await self.archive_for_connection(str(conn["id"]), user_id=user_id, reason="user_block")
        except RuntimeError:
            return

    async def reopen_for_connection(self, connection_id: str, *, user_id: str) -> dict[str, Any]:
        """Remove connection from the viewer's archived inbox."""
        result = await call_json_function(
            "fn_matrix_room_mappings",
            6,
            {"user_connection_id": connection_id, "user_id": user_id},
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_room_mappings mode 6 returned no row")
        return row
