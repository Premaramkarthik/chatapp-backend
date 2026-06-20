"""User report API models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReportCreateRequest(BaseModel):
    """Report another user."""

    reported_id: UUID
    reason: str = Field(..., min_length=3, max_length=200)
    description: str | None = Field(None, max_length=2000)


class ReportResponse(BaseModel):
    """User report row."""

    id: UUID
    reporter_id: UUID
    reported_id: UUID
    reason: str
    description: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
