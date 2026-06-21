"""Publish business events to Matrix rooms."""

from __future__ import annotations

from typing import Any

from core.logging.logger import get_logger, log_info
from domains.matrix.session.service import MatrixSessionService
from infrastructure.database.repositories.matrix_business_events import (
    PostgresMatrixBusinessEventRepository,
)
from infrastructure.matrix.client import payload_hash, send_room_event

logger = get_logger(__name__)


class MatrixBusinessEventService:
    """Publish deduplicated business events into Matrix rooms."""

    def __init__(
        self,
        *,
        sessions: MatrixSessionService | None = None,
        events: PostgresMatrixBusinessEventRepository | None = None,
    ) -> None:
        self._sessions = sessions or MatrixSessionService()
        self._events = events or PostgresMatrixBusinessEventRepository()

    async def publish(
        self,
        *,
        user: dict[str, Any],
        room_id: str,
        event_type: str,
        content: dict[str, Any],
        aggregate_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a custom room event and persist business event metadata."""
        session = await self._sessions.create_session(user=user)
        event_id = await send_room_event(
            access_token=session["access_token"],
            sender_mxid=session["matrix_user_id"],
            room_id=room_id,
            event_type=event_type,
            content=content,
        )
        row = await self._events.record(
            room_id=room_id,
            event_id=event_id,
            event_type=event_type,
            payload_hash=payload_hash(content),
            aggregate_id=aggregate_id,
        )
        log_info(
            logger,
            "Matrix business event published",
            matrix_category="room_events",
            room_id=room_id,
            event_type=event_type,
            event_id=event_id,
        )
        return row


matrix_business_event_service = MatrixBusinessEventService()


class MatrixEventService(MatrixBusinessEventService):
    """Alias for business event publishing used by HTTP routes."""

    async def publish(
        self,
        *,
        room_id: str,
        actor_user_id: str,
        event_type: str,
        payload: dict[str, Any],
        aggregate_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish a business event using the actor's Matrix session."""
        from infrastructure.database.repositories.users import PostgresUserRepository

        user_row = await PostgresUserRepository().get_by_id(actor_user_id)
        if user_row is None:
            raise ValueError("User not found")
        user = user_row.to_dict()
        return await super().publish(
            user=user,
            room_id=room_id,
            event_type=event_type,
            content=payload,
            aggregate_id=aggregate_id,
        )
