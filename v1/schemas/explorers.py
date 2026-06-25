"""Explorer and search API models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from domains.geo.location_payload import LocationFields


class LocationDisplay(BaseModel):
    """Computed display names for a location."""

    display_country: str | None = None
    display_state: str | None = None
    display_city: str | None = None


class ExplorerProfileResponse(BaseModel):
    """Explorer profile returned to the authenticated user."""

    user_id: UUID
    headline: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    home_country_id: int | None = None
    home_state_id: int | None = None
    home_city_id: int | None = None
    custom_home_country_name: str | None = None
    custom_home_state_name: str | None = None
    custom_home_city_name: str | None = None
    display_home_country: str | None = None
    display_home_state: str | None = None
    display_home_city: str | None = None
    languages: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    connection_availability: str = "open"
    visibility: str = "discoverable"
    last_active_at: datetime | None = None


class ExplorerProfileUpdateRequest(BaseModel):
    """Patch body for explorer profile."""

    headline: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    home_country_id: int | None = None
    home_state_id: int | None = None
    home_city_id: int | None = None
    custom_home_country_name: str | None = Field(None, max_length=100)
    custom_home_state_name: str | None = Field(None, max_length=100)
    custom_home_city_name: str | None = Field(None, max_length=150)
    languages: list[str] | None = None
    interests: list[str] | None = None
    connection_availability: Literal["open", "limited", "unavailable"] | None = None
    visibility: Literal["discoverable", "connections_only", "hidden"] | None = None

    @model_validator(mode="after")
    def validate_home_location(self) -> ExplorerProfileUpdateRequest:
        """Validate mutual exclusion for home location fields."""
        LocationFields(
            country_id=self.home_country_id,
            state_id=self.home_state_id,
            city_id=self.home_city_id,
            custom_country_name=self.custom_home_country_name,
            custom_state_name=self.custom_home_state_name,
            custom_city_name=self.custom_home_city_name,
        )
        return self


class TravelPlanDestinationInput(BaseModel):
    """Destination leg on a travel plan."""

    country_id: int | None = None
    state_id: int | None = None
    city_id: int | None = None
    custom_country_name: str | None = Field(None, max_length=100)
    custom_state_name: str | None = Field(None, max_length=100)
    custom_city_name: str | None = Field(None, max_length=150)
    arrival_date: date | None = None
    departure_date: date | None = None

    @model_validator(mode="after")
    def validate_destination_location(self) -> TravelPlanDestinationInput:
        """Validate mutual exclusion for destination location fields."""
        LocationFields(
            country_id=self.country_id,
            state_id=self.state_id,
            city_id=self.city_id,
            custom_country_name=self.custom_country_name,
            custom_state_name=self.custom_state_name,
            custom_city_name=self.custom_city_name,
        )
        return self


class TravelPlanCreateRequest(BaseModel):
    """Create a travel plan."""

    title: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_primary: bool = True
    destinations: list[TravelPlanDestinationInput] = Field(min_length=1)


class CurrentLocationUpdateRequest(BaseModel):
    """Update current location."""

    country_id: int | None = None
    state_id: int | None = None
    city_id: int | None = None
    custom_country_name: str | None = Field(None, max_length=100)
    custom_state_name: str | None = Field(None, max_length=100)
    custom_city_name: str | None = Field(None, max_length=150)
    latitude: float | None = None
    longitude: float | None = None

    @model_validator(mode="after")
    def validate_current_location(self) -> CurrentLocationUpdateRequest:
        """Validate mutual exclusion for current location fields."""
        LocationFields(
            country_id=self.country_id,
            state_id=self.state_id,
            city_id=self.city_id,
            custom_country_name=self.custom_country_name,
            custom_state_name=self.custom_state_name,
            custom_city_name=self.custom_city_name,
        )
        return self


# Search result models live in v1.schemas.connector_search for role-scoped APIs.
