"""Explorer privacy settings API models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PrivacySettingsResponse(BaseModel):
    """Explorer privacy settings."""

    user_id: UUID
    allow_connection_requests: bool = True
    allow_search_discovery: bool = True
    show_current_location: bool = True
    show_trip_dates: bool = True
    show_online_status: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PrivacySettingsUpdateRequest(BaseModel):
    """Patch body for explorer privacy settings."""

    allow_connection_requests: bool | None = None
    allow_search_discovery: bool | None = None
    show_current_location: bool | None = None
    show_trip_dates: bool | None = None
    show_online_status: bool | None = None
