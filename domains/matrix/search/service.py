"""Matrix search proxy and attachment metadata."""

from __future__ import annotations

from typing import Any

from core.config.settings import settings
from domains.matrix.session.service import MatrixSessionService
from infrastructure.database.repositories.conversations import PostgresConversationRepository
from infrastructure.database.repositories.matrix_attachments import (
    PostgresMatrixAttachmentRepository,
)
from infrastructure.matrix.client import search_messages as matrix_search_messages


class MatrixSearchService:
    """Proxy Matrix search and local attachment metadata queries."""

    def __init__(
        self,
        *,
        sessions: MatrixSessionService | None = None,
        attachments: PostgresMatrixAttachmentRepository | None = None,
        conversations: PostgresConversationRepository | None = None,
    ) -> None:
        self._sessions = sessions or MatrixSessionService()
        self._attachments = attachments or PostgresMatrixAttachmentRepository()
        self._conversations = conversations or PostgresConversationRepository()

    async def search_messages(
        self,
        *,
        user: dict[str, Any],
        search_term: str,
        room_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search messages via Synapse for the authenticated user."""
        session = await self._sessions.create_session(user=user)
        return await matrix_search_messages(
            access_token=session["access_token"],
            mxid=session["matrix_user_id"],
            search_term=search_term,
            room_id=room_id,
            limit=limit,
        )

    async def search_rooms(
        self,
        *,
        user: dict[str, Any],
        search_term: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search inbox rooms by peer display name or alias."""
        rows = await self._conversations.list_inbox(str(user["id"]), include_archived=True)
        needle = search_term.lower()
        matches: list[dict[str, Any]] = []
        for row in rows:
            mapping = row.get("mapping") or {}
            peer = row.get("peer") or {}
            haystack = " ".join(
                filter(
                    None,
                    [
                        str(peer.get("display_name", "")),
                        str(peer.get("email", "")),
                        str(mapping.get("room_alias", "")),
                        str(mapping.get("room_id", "")),
                    ],
                )
            ).lower()
            if needle in haystack:
                matches.append(row)
            if len(matches) >= limit:
                break
        return matches

    async def search_attachments(
        self,
        *,
        room_id: str | None = None,
        mimetype: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search locally stored attachment metadata."""
        return await self._attachments.search(room_id=room_id, mimetype=mimetype)

    async def record_attachment_metadata(
        self,
        *,
        room_id: str,
        event_id: str,
        uploaded_by_user_id: str,
        mimetype: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        thumbnail_event_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist attachment metadata after client upload."""
        return await self._attachments.upsert(
            room_id=room_id,
            event_id=event_id,
            mimetype=mimetype,
            size_bytes=size_bytes,
            sha256=sha256,
            thumbnail_event_id=thumbnail_event_id,
            uploaded_by_user_id=uploaded_by_user_id,
        )

    async def search_messages_for_user(
        self,
        *,
        user_id: str,
        query: str,
        room_id: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search messages and return a paginated response envelope."""
        if not settings.matrix.enabled:
            return {
                "items": [],
                "search_scope": "messages",
                "next_cursor": None,
                "note": "Matrix disabled",
            }
        user = {"id": user_id}
        items = await self.search_messages(
            user=user,
            search_term=query,
            room_id=room_id,
            limit=limit,
        )
        return {
            "items": items,
            "search_scope": "messages",
            "next_cursor": cursor,
            "note": None,
        }

    async def search_rooms_for_user(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search inbox rooms and return a paginated response envelope."""
        items = await self.search_rooms(
            user={"id": user_id},
            search_term=query,
            limit=limit,
        )
        return {"items": items, "search_scope": "rooms", "next_cursor": None, "note": None}

    async def search_attachments_envelope(
        self,
        *,
        room_id: str | None = None,
        mimetype: str | None = None,
    ) -> dict[str, Any]:
        """Search attachment metadata and return a response envelope."""
        items = await self.search_attachments(room_id=room_id, mimetype=mimetype)
        return {
            "items": items,
            "search_scope": "attachments",
            "next_cursor": None,
            "note": None,
        }


matrix_search_service = MatrixSearchService()
