"""Traveler and messenger profile repositories."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import row_from_jsonb


class PostgresTravelerRepository:
    """Postgres access for traveler and messenger profiles."""

    async def get_traveler_profile(self, user_id: str) -> dict[str, Any] | None:
        """Return traveler profile row."""
        result = await call_json_function("fn_traveler_profiles", 1, {"user_id": user_id})
        return row_from_jsonb(result)

    async def upsert_traveler_profile(
        self,
        user_id: str,
        *,
        headline: str | None = None,
        bio: str | None = None,
        avatar_url: str | None = None,
        home_country_iso: str | None = None,
        home_city_id: str | None = None,
        languages: list[str] | None = None,
        interests: list[str] | None = None,
        connection_availability: str | None = None,
        visibility: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a traveler profile."""
        payload: dict[str, Any] = {"user_id": user_id}
        if headline is not None:
            payload["headline"] = headline
        if bio is not None:
            payload["bio"] = bio
        if avatar_url is not None:
            payload["avatar_url"] = avatar_url
        if home_country_iso is not None:
            payload["home_country_iso"] = home_country_iso
        if home_city_id is not None:
            payload["home_city_id"] = home_city_id
        if languages is not None:
            payload["languages"] = languages
        if interests is not None:
            payload["interests"] = interests
        if connection_availability is not None:
            payload["connection_availability"] = connection_availability
        if visibility is not None:
            payload["visibility"] = visibility

        result = await call_json_function("fn_traveler_profiles", 2, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_traveler_profiles mode 2 returned no row")
        return row

    async def upsert_privacy_settings(
        self,
        user_id: str,
        **fields: bool,
    ) -> dict[str, Any]:
        """Update privacy flags and rebuild discovery snapshot."""
        payload: dict[str, Any] = {"user_id": user_id, **fields}
        result = await call_json_function("fn_user_privacy_settings", 2, payload)
        return row_from_jsonb(result) or {}

    async def upsert_messenger_profile(
        self,
        user_id: str,
        *,
        home_country_iso: str | None = None,
        preferred_destination_countries: list[str] | None = None,
        last_search_country_iso: str | None = None,
        last_search_city_id: str | None = None,
        bio: str | None = None,
    ) -> dict[str, Any]:
        """Create or update messenger profile (search preferences)."""
        payload: dict[str, Any] = {"user_id": user_id}
        if home_country_iso is not None:
            payload["home_country_iso"] = home_country_iso
        if preferred_destination_countries is not None:
            payload["preferred_destination_countries"] = preferred_destination_countries
        if last_search_country_iso is not None:
            payload["last_search_country_iso"] = last_search_country_iso
        if last_search_city_id is not None:
            payload["last_search_city_id"] = last_search_city_id
        if bio is not None:
            payload["bio"] = bio

        result = await call_json_function("fn_messenger_profiles", 2, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_messenger_profiles mode 2 returned no row")
        return row
