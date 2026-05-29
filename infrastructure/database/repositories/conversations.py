"""Tinode conversation mappings."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresConversationRepository:
    """Postgres access for tinode_conversation_mappings."""

    async def get_by_connection(self, connection_id: str) -> dict[str, Any] | None:
        """Return mapping for a user connection."""
        result = await call_json_function(
            "fn_tinode_conversation_mappings",
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
        """Create or return a Tinode topic mapping for a connection."""
        result = await call_json_function(
            "fn_tinode_conversation_mappings",
            2,
            {
                "user_connection_id": connection_id,
                "created_by_user_id": created_by_user_id,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_tinode_conversation_mappings mode 2 returned no row")
        return row

    async def list_inbox(
        self,
        user_id: str,
        *,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """List active connections with peer and mapping metadata."""
        result = await call_json_function(
            "fn_tinode_conversation_mappings",
            3,
            {"user_id": user_id, "include_archived": include_archived},
        )
        return list_from_jsonb(result)

    async def update_mapping(
        self,
        *,
        connection_id: str,
        tinode_topic_id: str | None = None,
        tinode_topic_name: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Update topic fields or provisioning status."""
        payload: dict[str, Any] = {"user_connection_id": connection_id}
        if tinode_topic_id is not None:
            payload["tinode_topic_id"] = tinode_topic_id
        if tinode_topic_name is not None:
            payload["tinode_topic_name"] = tinode_topic_name
        if status is not None:
            payload["status"] = status
        result = await call_json_function("fn_tinode_conversation_mappings", 4, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_tinode_conversation_mappings mode 4 returned no row")
        return row

    async def archive_for_connection(self, connection_id: str) -> dict[str, Any]:
        """Mark mapping archived for a connection."""
        result = await call_json_function(
            "fn_tinode_conversation_mappings",
            5,
            {"user_connection_id": connection_id},
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_tinode_conversation_mappings mode 5 returned no row")
        return row

    async def archive_between_users(self, user_id: str, other_user_id: str) -> None:
        """Archive conversation mapping when users share an active connection."""
        from infrastructure.database.repositories.matching import PostgresMatchingRepository

        conn = await PostgresMatchingRepository().get_connection_between(user_id, other_user_id)
        if conn is None:
            return
        try:
            await self.archive_for_connection(str(conn["id"]))
        except RuntimeError:
            return
