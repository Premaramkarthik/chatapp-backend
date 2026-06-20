"""User privacy settings repository."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import row_from_jsonb


class PostgresPrivacyRepository:
    """Postgres access for explorer privacy settings."""

    async def get_privacy_settings(self, user_id: str) -> dict[str, Any] | None:
        """Return privacy settings row."""
        result = await call_json_function("fn_user_privacy_settings", 1, {"user_id": user_id})
        return row_from_jsonb(result)

    async def upsert_privacy_settings(
        self,
        user_id: str,
        **fields: bool,
    ) -> dict[str, Any]:
        """Update privacy flags and rebuild discovery snapshot."""
        payload: dict[str, Any] = {"user_id": user_id, **fields}
        result = await call_json_function("fn_user_privacy_settings", 2, payload)
        return row_from_jsonb(result) or {}
