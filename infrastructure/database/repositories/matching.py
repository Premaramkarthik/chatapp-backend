"""Connection requests, connections, and blocks."""

from __future__ import annotations

from typing import Any

from domains.matching.policies import CONNECTION_REQUEST_TTL_DAYS
from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import (
    list_from_jsonb,
    map_social_db_error,
    row_from_jsonb,
)


class PostgresMatchingRepository:
    """Postgres access for social connections."""

    async def is_blocked(self, user_id: str, other_id: str) -> bool:
        """Return True if either user blocked the other."""
        result = await call_json_function(
            "fn_user_blocks",
            1,
            {"user_id": user_id, "other_user_id": other_id},
        )
        row = row_from_jsonb(result)
        return bool(row and row.get("blocked"))

    async def create_block(self, blocker_id: str, blocked_id: str, reason: str | None) -> dict:
        """Block another user."""
        result = await call_json_function(
            "fn_user_blocks",
            2,
            {
                "blocker_id": blocker_id,
                "blocked_id": blocked_id,
                "reason": reason,
            },
        )
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_user_blocks mode 2 returned no row")
        from infrastructure.database.repositories.conversations import (
            PostgresConversationRepository,
        )

        await PostgresConversationRepository().archive_between_users(blocker_id, blocked_id)
        return row

    async def create_connection_request(
        self,
        requester_id: str,
        recipient_id: str,
        message: str | None,
    ) -> dict[str, Any]:
        """Create a pending connection request."""
        try:
            result = await call_json_function(
                "fn_connection_requests",
                1,
                {
                    "requester_id": requester_id,
                    "recipient_id": recipient_id,
                    "message": message,
                    "ttl_days": CONNECTION_REQUEST_TTL_DAYS,
                },
            )
        except Exception as exc:
            map_social_db_error(exc)
            raise
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_connection_requests mode 1 returned no row")
        return row

    async def get_request(self, request_id: str) -> dict[str, Any] | None:
        """Return a connection request by id."""
        result = await call_json_function(
            "fn_connection_requests",
            2,
            {"request_id": request_id},
        )
        return row_from_jsonb(result)

    async def list_incoming_requests(self, recipient_id: str) -> list[dict[str, Any]]:
        """List pending incoming requests."""
        result = await call_json_function(
            "fn_connection_requests",
            3,
            {"recipient_id": recipient_id},
        )
        return list_from_jsonb(result)

    async def accept_request(self, request_id: str, recipient_id: str) -> dict[str, Any]:
        """Accept a request and create a symmetric connection."""
        try:
            result = await call_json_function(
                "fn_connection_requests",
                4,
                {"request_id": request_id, "recipient_id": recipient_id},
            )
        except Exception as exc:
            map_social_db_error(exc)
            raise
        row = row_from_jsonb(result)
        if row is None:
            raise ValueError("not_found")
        return row

    async def reject_request(self, request_id: str, recipient_id: str) -> dict[str, Any]:
        """Reject a pending request."""
        try:
            result = await call_json_function(
                "fn_connection_requests",
                5,
                {"request_id": request_id, "recipient_id": recipient_id},
            )
        except Exception as exc:
            map_social_db_error(exc)
            raise
        row = row_from_jsonb(result)
        if row is None:
            raise ValueError("not_found")
        return row

    async def get_connection_between(self, user_id: str, other_id: str) -> dict[str, Any] | None:
        """Return active connection between two users."""
        result = await call_json_function(
            "fn_user_connections",
            2,
            {"user_id": user_id, "other_user_id": other_id},
        )
        return row_from_jsonb(result)

    async def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        """Return connection by id."""
        result = await call_json_function(
            "fn_user_connections",
            1,
            {"connection_id": connection_id},
        )
        return row_from_jsonb(result)
