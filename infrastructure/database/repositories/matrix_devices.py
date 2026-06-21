"""Matrix device metadata persistence."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresMatrixDeviceRepository:
    """Postgres access for Matrix device metadata."""

    async def upsert(
        self,
        *,
        user_id: str,
        device_id: str,
        device_label: str | None = None,
        trust_level: str | None = None,
        last_seen_at: str | None = None,
    ) -> dict[str, Any]:
        """Create or update device metadata."""
        result = await call_json_function(
            "fn_matrix_user_devices",
            1,
            {
                "user_id": user_id,
                "device_id": device_id,
                "device_label": device_label,
                "trust_level": trust_level,
                "last_seen_at": last_seen_at,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_user_devices mode 1 returned no row")
        return row

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """List devices for a user."""
        result = await call_json_function(
            "fn_matrix_user_devices",
            2,
            {"user_id": user_id},
        )
        return list_from_jsonb(result)

    async def get(self, *, user_id: str, device_id: str) -> dict[str, Any] | None:
        """Return one device row."""
        result = await call_json_function(
            "fn_matrix_user_devices",
            3,
            {"user_id": user_id, "device_id": device_id},
        )
        return row_from_jsonb(result)

    async def delete(self, *, user_id: str, device_id: str) -> dict[str, Any] | None:
        """Delete device metadata."""
        result = await call_json_function(
            "fn_matrix_user_devices",
            4,
            {"user_id": user_id, "device_id": device_id},
        )
        return row_from_jsonb(result)

    async def verify(
        self,
        *,
        user_id: str,
        device_id: str,
        trust_level: str = "verified",
    ) -> dict[str, Any]:
        """Mark a device as verified."""
        result = await call_json_function(
            "fn_matrix_user_devices",
            5,
            {
                "user_id": user_id,
                "device_id": device_id,
                "trust_level": trust_level,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_user_devices mode 5 returned no row")
        return row
