"""Explorer and connector profile repositories."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import row_from_jsonb


class PostgresExplorerRepository:
    """Postgres access for explorer and connector profiles."""

    async def get_explorer_profile(self, user_id: str) -> dict[str, Any] | None:
        """Return explorer profile row."""
        result = await call_json_function("fn_explorer_profiles", 1, {"user_id": user_id})
        return row_from_jsonb(result)

    async def upsert_explorer_profile(
        self,
        user_id: str,
        *,
        headline: str | None = None,
        bio: str | None = None,
        avatar_url: str | None = None,
        home_country_id: int | None = None,
        home_state_id: int | None = None,
        home_city_id: int | None = None,
        custom_home_country_name: str | None = None,
        custom_home_state_name: str | None = None,
        custom_home_city_name: str | None = None,
        languages: list[str] | None = None,
        interests: list[str] | None = None,
        connection_availability: str | None = None,
        visibility: str | None = None,
    ) -> dict[str, Any]:
        """Create or update an explorer profile."""
        payload: dict[str, Any] = {"user_id": user_id}
        field_map = {
            "headline": headline,
            "bio": bio,
            "avatar_url": avatar_url,
            "home_country_id": home_country_id,
            "home_state_id": home_state_id,
            "home_city_id": home_city_id,
            "custom_home_country_name": custom_home_country_name,
            "custom_home_state_name": custom_home_state_name,
            "custom_home_city_name": custom_home_city_name,
            "languages": languages,
            "interests": interests,
            "connection_availability": connection_availability,
            "visibility": visibility,
        }
        for key, value in field_map.items():
            if value is not None:
                payload[key] = value

        result = await call_json_function("fn_explorer_profiles", 2, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_explorer_profiles mode 2 returned no row")
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

    async def upsert_connector_profile(
        self,
        user_id: str,
        *,
        home_country_id: int | None = None,
        home_state_id: int | None = None,
        home_city_id: int | None = None,
        custom_home_country_name: str | None = None,
        custom_home_state_name: str | None = None,
        custom_home_city_name: str | None = None,
        preferred_destination_countries: list[str] | None = None,
        last_search_country_id: int | None = None,
        last_search_state_id: int | None = None,
        last_search_city_id: int | None = None,
        custom_last_search_country_name: str | None = None,
        custom_last_search_state_name: str | None = None,
        custom_last_search_city_name: str | None = None,
        bio: str | None = None,
    ) -> dict[str, Any]:
        """Create or update connector profile (search preferences)."""
        payload: dict[str, Any] = {"user_id": user_id}
        field_map = {
            "home_country_id": home_country_id,
            "home_state_id": home_state_id,
            "home_city_id": home_city_id,
            "custom_home_country_name": custom_home_country_name,
            "custom_home_state_name": custom_home_state_name,
            "custom_home_city_name": custom_home_city_name,
            "preferred_destination_countries": preferred_destination_countries,
            "last_search_country_id": last_search_country_id,
            "last_search_state_id": last_search_state_id,
            "last_search_city_id": last_search_city_id,
            "custom_last_search_country_name": custom_last_search_country_name,
            "custom_last_search_state_name": custom_last_search_state_name,
            "custom_last_search_city_name": custom_last_search_city_name,
            "bio": bio,
        }
        for key, value in field_map.items():
            if value is not None:
                payload[key] = value

        result = await call_json_function("fn_connector_profiles", 2, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_connector_profiles mode 2 returned no row")
        return row
