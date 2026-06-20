"""Connector profile API models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from domains.geo.location_payload import LocationFields


class ConnectorProfileResponse(BaseModel):
    """Connector profile returned to the authenticated user."""

    user_id: UUID
    bio: str | None = None
    home_country_id: int | None = None
    home_state_id: int | None = None
    home_city_id: int | None = None
    custom_home_country_name: str | None = None
    custom_home_state_name: str | None = None
    custom_home_city_name: str | None = None
    display_home_country: str | None = None
    display_home_state: str | None = None
    display_home_city: str | None = None
    preferred_destination_countries: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConnectorProfileUpdateRequest(BaseModel):
    """Patch body for connector profile."""

    bio: str | None = None
    home_country_id: int | None = None
    home_state_id: int | None = None
    home_city_id: int | None = None
    custom_home_country_name: str | None = Field(None, max_length=100)
    custom_home_state_name: str | None = Field(None, max_length=100)
    custom_home_city_name: str | None = Field(None, max_length=150)
    preferred_destination_countries: list[str] | None = None

    @field_validator("preferred_destination_countries")
    @classmethod
    def normalize_destination_countries(cls, value: list[str] | None) -> list[str] | None:
        """Normalize ISO2 country codes to uppercase."""
        if value is None:
            return None
        return [code.strip().upper() for code in value if code.strip()]

    @model_validator(mode="after")
    def validate_home_location(self) -> ConnectorProfileUpdateRequest:
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
