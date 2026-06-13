"""Normalize and validate location ID vs custom-name payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class LocationFields(BaseModel):
    """Six-column location pattern shared by profiles, trips, and current location."""

    country_id: int | None = None
    state_id: int | None = None
    city_id: int | None = None
    custom_country_name: str | None = Field(None, max_length=100)
    custom_state_name: str | None = Field(None, max_length=100)
    custom_city_name: str | None = Field(None, max_length=150)

    @model_validator(mode="after")
    def validate_mutual_exclusion(self) -> LocationFields:
        """Ensure IDs and custom names are not both set for the same level."""
        pairs = (
            ("country_id", "custom_country_name"),
            ("state_id", "custom_state_name"),
            ("city_id", "custom_city_name"),
        )
        for id_field, custom_field in pairs:
            id_val = getattr(self, id_field)
            custom_val = getattr(self, custom_field)
            if custom_val is not None:
                custom_val = custom_val.strip()
                if not custom_val:
                    raise ValueError(f"{custom_field} cannot be empty")
                setattr(self, custom_field, custom_val)
            if id_val is not None and custom_val:
                raise ValueError(f"Cannot set both {id_field} and {custom_field}")
        return self


def normalize_location_payload(
    *,
    country_id: int | None = None,
    state_id: int | None = None,
    city_id: int | None = None,
    custom_country_name: str | None = None,
    custom_state_name: str | None = None,
    custom_city_name: str | None = None,
    prefix: str = "",
) -> dict[str, Any]:
    """Validate location fields and return a DB payload dict with optional key prefix."""
    fields = LocationFields(
        country_id=country_id,
        state_id=state_id,
        city_id=city_id,
        custom_country_name=custom_country_name,
        custom_state_name=custom_state_name,
        custom_city_name=custom_city_name,
    )
    mapping = {
        "country_id": fields.country_id,
        "state_id": fields.state_id,
        "city_id": fields.city_id,
        "custom_country_name": fields.custom_country_name,
        "custom_state_name": fields.custom_state_name,
        "custom_city_name": fields.custom_city_name,
    }
    if not prefix:
        return {k: v for k, v in mapping.items() if v is not None}
    return {
        f"{prefix}{k}" if prefix.endswith("_") else f"{prefix}_{k}": v
        for k, v in mapping.items()
        if v is not None
    }


def normalize_home_location_payload(**kwargs: Any) -> dict[str, Any]:
    """Map home location API fields to explorer_profiles column names."""
    fields = LocationFields(
        country_id=kwargs.get("home_country_id"),
        state_id=kwargs.get("home_state_id"),
        city_id=kwargs.get("home_city_id"),
        custom_country_name=kwargs.get("custom_home_country_name"),
        custom_state_name=kwargs.get("custom_home_state_name"),
        custom_city_name=kwargs.get("custom_home_city_name"),
    )
    mapping = {
        "home_country_id": fields.country_id,
        "home_state_id": fields.state_id,
        "home_city_id": fields.city_id,
        "custom_home_country_name": fields.custom_country_name,
        "custom_home_state_name": fields.custom_state_name,
        "custom_home_city_name": fields.custom_city_name,
    }
    return {k: v for k, v in mapping.items() if v is not None}
