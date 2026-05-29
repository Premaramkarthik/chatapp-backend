"""Chat conversation API models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationProvisionRequest(BaseModel):
    """Provision Tinode topic for an existing connection."""

    connection_id: UUID


class ConversationMappingSummary(BaseModel):
    """Subset of tinode_conversation_mappings for API responses."""

    id: UUID | None = None
    user_connection_id: UUID | None = None
    tinode_topic_id: str | None = None
    tinode_topic_name: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationResponse(BaseModel):
    """Tinode conversation mapping."""

    id: UUID
    user_connection_id: UUID
    tinode_topic_id: str
    tinode_topic_name: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime | None = None


class TinodeSessionResponse(BaseModel):
    """Credentials for Tinode WebSocket login."""

    web_url: str
    secret: str
    user_id: UUID
    tinode_user_id: str
    expires_in: int = Field(description="Suggested secret lifetime in seconds")


class InboxPeer(BaseModel):
    """Other participant in a 1:1 connection."""

    user_id: UUID
    display_name: str
    email: str | None = None
    tinode_user_id: str | None = None


class InboxItem(BaseModel):
    """One inbox row: connection + optional mapping + peer."""

    connection_id: UUID
    connection_status: str
    connected_at: datetime | None = None
    peer: InboxPeer
    mapping: ConversationMappingSummary | None = None
    can_chat: bool


class InboxResponse(BaseModel):
    """Chat inbox for the current user."""

    items: list[InboxItem]
