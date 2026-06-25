"""Screen-oriented connection hub API models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

HistoryKind = Literal[
    "request_rejected",
    "request_cancelled",
    "request_expired",
    "connection_removed",
]


class ConnectionPeerSummary(BaseModel):
    """Enriched peer card for connection screens."""

    user_id: UUID
    display_name: str | None = None
    account_mode: str | None = None
    avatar_url: str | None = None
    headline: str | None = None
    home_label: str | None = None
    destination_country_iso: str | None = None
    destination_city_name: str | None = None
    languages: list[str] = Field(default_factory=list)
    last_active_at: datetime | None = None


class IncomingRequestItem(BaseModel):
    """Pending incoming connection request with peer context."""

    request_id: UUID
    message: str | None = None
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    peer: ConnectionPeerSummary


class SentRequestItem(BaseModel):
    """Pending outgoing connection request with peer context."""

    request_id: UUID
    message: str | None = None
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    peer: ConnectionPeerSummary


class ActiveConnectionItem(BaseModel):
    """Active connection with peer context and chat hints."""

    connection_id: UUID
    connected_at: datetime
    peer: ConnectionPeerSummary
    can_chat: bool = False
    conversation_status: str | None = None
    is_archived: bool = False
    can_archive: bool = False
    can_reopen: bool = False


class HistoryItem(BaseModel):
    """Terminal connection request or removed connection."""

    kind: HistoryKind
    occurred_at: datetime
    peer: ConnectionPeerSummary
    message: str | None = None
    request_id: UUID | None = None
    connection_id: UUID | None = None


class ConnectionsSummaryResponse(BaseModel):
    """Tab badge counts for the connections hub."""

    incoming_pending: int = 0
    sent_pending: int = 0
    active: int = 0
    history_count: int = 0


class IncomingRequestsResponse(BaseModel):
    """Incoming tab payload."""

    items: list[IncomingRequestItem]


class SentRequestsResponse(BaseModel):
    """Sent tab payload."""

    items: list[SentRequestItem]


class ActiveConnectionsResponse(BaseModel):
    """Active tab payload."""

    items: list[ActiveConnectionItem]


class HistoryResponse(BaseModel):
    """History tab payload."""

    items: list[HistoryItem]
