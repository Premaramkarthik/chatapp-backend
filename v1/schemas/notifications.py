"""Notification API models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationResponse(BaseModel):
    """In-app notification row."""

    id: UUID
    user_id: UUID
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime
