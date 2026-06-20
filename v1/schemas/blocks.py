"""Block API models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class BlockCreateRequest(BaseModel):
    """Block another user."""

    blocked_id: UUID
    reason: str | None = Field(None, max_length=500)


class BlockResponse(BaseModel):
    """Block row."""

    id: UUID
    blocker_id: UUID
    blocked_id: UUID
    reason: str | None = None
    created_at: datetime
