"""In-app notification repository."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresNotificationRepository:
    """Postgres access for notifications."""

    async def create_notification(
        self,
        user_id: str,
        notification_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a notification for a user."""
        result = await call_json_function(
            "fn_notifications",
            1,
            {
                "user_id": user_id,
                "type": notification_type,
                "payload": payload or {},
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_notifications mode 1 returned no row")
        return row

    async def list_notifications(
        self,
        user_id: str,
        *,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List notifications for a user."""
        result = await call_json_function(
            "fn_notifications",
            2,
            {"user_id": user_id, "unread_only": unread_only},
        )
        return list_from_jsonb(result)

    async def mark_read(self, user_id: str, notification_id: str) -> dict[str, Any] | None:
        """Mark a notification as read."""
        result = await call_json_function(
            "fn_notifications",
            3,
            {"user_id": user_id, "notification_id": notification_id},
        )
        return row_from_jsonb(result)
