"""Explorer-scoped search API models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConnectorSearchResult(BaseModel):
    """Public connector card for explorer route search results."""

    user_id: UUID
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    home_country_label: str | None = None
    home_city_label: str | None = None
    preferred_destination_countries: list[str] = Field(default_factory=list)
    last_active_at: datetime | None = None


class ConnectorSearchResponse(BaseModel):
    """Paginated connector route search response."""

    hits: list[ConnectorSearchResult]
    total: int
    limit: int
    offset: int


class ExplorerUserSearchHit(BaseModel):
    """Connector user hit from explorer username search."""

    user_id: UUID
    display_name: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    home_label: str | None = None
    role: str | None = None
    bio: str | None = None
    preferred_destination_countries: list[str] = Field(default_factory=list)


class ExplorerUserSearchResponse(BaseModel):
    """Paginated username search response for explorers."""

    hits: list[ExplorerUserSearchHit]
    total: int
    page: int
    limit: int
