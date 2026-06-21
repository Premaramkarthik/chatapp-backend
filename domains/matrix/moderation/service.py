"""Matrix moderation side effects."""

from __future__ import annotations

from infrastructure.database.connection import call_json_function
from infrastructure.database.repositories.conversations import PostgresConversationRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository


class MatrixModerationService:
    """Apply chat side effects for blocks and reports."""

    def __init__(
        self,
        *,
        conversations: PostgresConversationRepository | None = None,
        matching: PostgresMatchingRepository | None = None,
    ) -> None:
        self._conversations = conversations or PostgresConversationRepository()
        self._matching = matching or PostgresMatchingRepository()

    async def on_user_blocked(self, *, blocker_id: str, blocked_id: str) -> None:
        """Archive DM mapping when users block each other."""
        await self._conversations.archive_between_users(blocker_id, blocked_id)

    async def on_user_reported(
        self,
        *,
        report_id: str,
        reporter_id: str,
        reported_id: str,
    ) -> None:
        """Link a user report to an existing DM room when available."""
        conn = await self._matching.get_connection_between(reporter_id, reported_id)
        if conn is None:
            return
        mapping = await self._conversations.get_by_connection(str(conn["id"]))
        if mapping is None:
            return
        await call_json_function(
            "fn_matrix_reports",
            1,
            {
                "report_id": report_id,
                "room_id": mapping.get("room_id"),
            },
        )


matrix_moderation_service = MatrixModerationService()
