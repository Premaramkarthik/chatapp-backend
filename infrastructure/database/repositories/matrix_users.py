"""Matrix user mapping persistence."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import row_from_jsonb


class PostgresMatrixUserRepository:
    """Postgres access for Matrix user mappings."""

    async def upsert(
        self,
        *,
        user_id: str,
        mxid: str,
        localpart: str | None = None,
        password_encrypted: str = "",
        provision_status: str = "active",
    ) -> dict[str, Any]:
        """Create or update a Matrix user mapping."""
        result = await call_json_function(
            "fn_matrix_user_mappings",
            1,
            {
                "user_id": user_id,
                "mxid": mxid,
                "localpart": localpart,
                "password_encrypted": password_encrypted,
                "provision_status": provision_status,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_matrix_user_mappings mode 1 returned no row")
        return row

    async def get_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        """Return mapping for a local user id."""
        result = await call_json_function(
            "fn_matrix_user_mappings",
            2,
            {"user_id": user_id},
        )
        return row_from_jsonb(result)

    async def get_by_keycloak_sub(self, keycloak_sub: str) -> dict[str, Any] | None:
        """Return mapping for a Keycloak subject."""
        result = await call_json_function(
            "fn_matrix_user_mappings",
            3,
            {"keycloak_sub": keycloak_sub},
        )
        return row_from_jsonb(result)

    async def get_by_mxid(self, mxid: str) -> dict[str, Any] | None:
        """Return mapping for a Matrix user id."""
        result = await call_json_function(
            "fn_matrix_user_mappings",
            4,
            {"mxid": mxid},
        )
        return row_from_jsonb(result)
