"""Connector-scoped search API models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ExplorerSearchResult(BaseModel):
    """Public explorer card for connector route search results."""

    user_id: UUID
    display_name: str | None = None
    headline: str | None = None
    avatar_url: str | None = None
    destination_country_iso: str | None = None
    destination_city_name: str | None = None
    current_country_iso: str | None = None
    languages: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    connection_availability: str = "open"
    last_active_at: datetime | None = None


class ExplorerSearchResponse(BaseModel):
    """Paginated explorer route search response."""

    hits: list[ExplorerSearchResult]
    total: int
    limit: int
    offset: int


class ConnectorUserSearchHit(BaseModel):
    """Explorer user hit from connector username search."""

    user_id: UUID
    display_name: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    home_label: str | None = None
    role: str | None = None
    headline: str | None = None
    destination_country_iso: str | None = None
    connection_availability: str = "open"


class ConnectorUserSearchResponse(BaseModel):
    """Paginated username search response for connectors."""

    hits: list[ConnectorUserSearchHit]
    total: int
    page: int
    limit: int
