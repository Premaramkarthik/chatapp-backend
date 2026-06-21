"""Search API request/response schemas."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SearchUserHit(BaseModel):
    """User search result document."""

    id: str
    username: str | None = None
    full_name: str | None = None
    profile_photo: str | None = None
    role: str | None = None
    city: str | None = None
    country: str | None = None
    verified: bool = False


class SearchTravelerHit(BaseModel):
    """Traveler search result document."""

    id: str
    user_id: str
    from_city: str | None = None
    to_city: str | None = None
    from_country: str | None = None
    to_country: str | None = None
    departure_date: int | None = None
    verified: bool = False


class SearchCityHit(BaseModel):
    """City search result document."""

    id: str
    city_name: str | None = None
    state_name: str | None = None
    country_name: str | None = None
    country_iso2: str | None = None


class SearchCountryHit(BaseModel):
    """Country search result document."""

    id: str
    country_name: str | None = None
    iso2: str | None = None


class SearchStateHit(BaseModel):
    """State search result document."""

    id: str
    state_name: str | None = None
    country_name: str | None = None
    country_iso2: str | None = None


class GlobalSearchResponse(BaseModel):
    """Grouped global search response."""

    users: list[SearchUserHit] = Field(default_factory=list)
    travelers: list[SearchTravelerHit] = Field(default_factory=list)
    cities: list[SearchCityHit] = Field(default_factory=list)
    countries: list[SearchCountryHit] = Field(default_factory=list)
    states: list[SearchStateHit] = Field(default_factory=list)
    requests: list[Any] = Field(default_factory=list)


class SearchListResponse(BaseModel):
    """Paginated search list response."""

    hits: list[dict[str, Any]]
    total: int
    page: int = 1
    limit: int = 20


class SuggestionItem(BaseModel):
    """Search suggestion chip."""

    id: str
    label: str
    kind: str = "query"
    score: float = 0.0


class SuggestionsResponse(BaseModel):
    """Suggestion list response."""

    items: list[SuggestionItem] = Field(default_factory=list)


class SearchEventRequest(BaseModel):
    """Client-submitted search analytics event."""

    query: str
    result_type: str
    result_id: str | None = None
    clicked: bool = False


class SearchEventResponse(BaseModel):
    """Acknowledgement for recorded search events."""

    recorded: bool = True
    event_id: UUID | None = None
