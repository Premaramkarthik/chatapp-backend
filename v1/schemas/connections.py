"""Connection request API models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConnectionRequestCreate(BaseModel):
    """Create a connection request to a traveler."""

    recipient_id: UUID
    message: str | None = Field(None, max_length=500)


class ConnectionRequestResponse(BaseModel):
    """Connection request row."""

    id: UUID
    requester_id: UUID
    recipient_id: UUID
    status: str
    message: str | None = None
    expires_at: datetime | None = None
    created_at: datetime


class UserConnectionResponse(BaseModel):
    """Established connection between two users."""

    id: UUID
    user_a_id: UUID
    user_b_id: UUID
    status: str
    connected_at: datetime
