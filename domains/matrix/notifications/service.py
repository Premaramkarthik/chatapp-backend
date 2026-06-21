"""Matrix notification preference CRUD."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import row_from_jsonb


class MatrixNotificationService:
    """Manage Matrix-related notification preferences."""

    async def get_preferences(self, user_id: str) -> dict[str, Any]:
        """Return notification preferences, creating defaults when missing."""
        result = await call_json_function(
            "fn_matrix_notification_preferences",
            2,
            {"user_id": user_id},
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_notification_preferences mode 2 returned no row")
        return row

    async def update_preferences(self, user_id: str, **fields: Any) -> dict[str, Any]:
        """Patch notification preferences for a user."""
        quiet_start = fields.get("quiet_hours_start")
        quiet_end = fields.get("quiet_hours_end")
        if hasattr(quiet_start, "isoformat"):
            quiet_start = quiet_start.isoformat()
        if hasattr(quiet_end, "isoformat"):
            quiet_end = quiet_end.isoformat()

        payload: dict[str, Any] = {"user_id": user_id}
        for key in (
            "mentions_enabled",
            "invites_enabled",
            "messages_enabled",
            "business_events_enabled",
        ):
            if key in fields and fields[key] is not None:
                payload[key] = fields[key]
        if quiet_start is not None:
            payload["quiet_hours_start"] = quiet_start
        if quiet_end is not None:
            payload["quiet_hours_end"] = quiet_end

        result = await call_json_function("fn_matrix_notification_preferences", 1, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_notification_preferences mode 1 returned no row")
        return row


matrix_notification_service = MatrixNotificationService()
