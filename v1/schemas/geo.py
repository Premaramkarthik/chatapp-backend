"""Geo autocomplete API models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CountryItem(BaseModel):
    """Country row for autocomplete."""

    id: int
    iso2: str
    iso3: str
    name: str
    phone_code: str | None = None


class StateItem(BaseModel):
    """State row for autocomplete."""

    id: int
    country_id: int
    state_code: str | None = None
    name: str


class CityItem(BaseModel):
    """City row for autocomplete."""

    id: int
    country_id: int
    state_id: int
    name: str


class GeoListResponse(BaseModel):
    """Paginated-style list wrapper for geo autocomplete."""

    items: list[CountryItem | StateItem | CityItem] = Field(default_factory=list)
    count: int = 0
