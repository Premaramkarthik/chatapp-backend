"""Traveler and search API models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TravelerProfileResponse(BaseModel):
    """Traveler profile returned to the authenticated user."""

    user_id: UUID
    headline: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    home_country_iso: str | None = None
    home_city_id: UUID | None = None
    languages: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    connection_availability: str = "open"
    visibility: str = "discoverable"
    last_active_at: datetime | None = None


class TravelerProfileUpdateRequest(BaseModel):
    """Patch body for traveler profile."""

    headline: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    home_country_iso: str | None = Field(None, min_length=2, max_length=2)
    home_city_id: UUID | None = None
    languages: list[str] | None = None
    interests: list[str] | None = None
    connection_availability: Literal["open", "limited", "unavailable"] | None = None
    visibility: Literal["discoverable", "connections_only", "hidden"] | None = None


class TravelPlanDestinationInput(BaseModel):
    """Destination leg on a travel plan."""

    country_iso: str = Field(..., min_length=2, max_length=2)
    city_id: UUID | None = None
    arrival_date: date | None = None
    departure_date: date | None = None


class TravelPlanCreateRequest(BaseModel):
    """Create a travel plan."""

    title: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_primary: bool = True
    destinations: list[TravelPlanDestinationInput] = Field(min_length=1)


class CurrentLocationUpdateRequest(BaseModel):
    """Update current location."""

    country_iso: str | None = Field(None, min_length=2, max_length=2)
    city_id: UUID | None = None
    latitude: float | None = None
    longitude: float | None = None


class TravelerSearchResult(BaseModel):
    """Public traveler card for search results."""

    user_id: UUID
    display_name: str | None = None
    headline: str | None = None
    avatar_url: str | None = None
    destination_country_iso: str
    destination_city_name: str | None = None
    current_country_iso: str | None = None
    languages: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    connection_availability: str = "open"
    last_active_at: datetime | None = None


class TravelerSearchResponse(BaseModel):
    """Paginated traveler search response."""

    hits: list[TravelerSearchResult]
    total: int
    limit: int
    offset: int
