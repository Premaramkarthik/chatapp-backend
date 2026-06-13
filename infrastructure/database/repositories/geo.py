"""Read-only geo master data queries via fn_geo stored function."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresGeoRepository:
    """Search geo_countries, geo_states, and geo_cities through fn_geo."""

    async def search_countries(self, search: str, *, limit: int) -> list[dict[str, Any]]:
        """Return countries matching search (or top N when search empty)."""
        result = await call_json_function(
            "fn_geo",
            1,
            {"search": search.strip(), "limit": limit},
        )
        return list_from_jsonb(result)

    async def search_states(
        self,
        country_id: int,
        search: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return states for a country matching search."""
        result = await call_json_function(
            "fn_geo",
            2,
            {"country_id": country_id, "search": search.strip(), "limit": limit},
        )
        return list_from_jsonb(result)

    async def search_cities(
        self,
        state_id: int,
        search: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return cities for a state matching search."""
        result = await call_json_function(
            "fn_geo",
            3,
            {"state_id": state_id, "search": search.strip(), "limit": limit},
        )
        return list_from_jsonb(result)

    async def get_country(self, country_id: int) -> dict[str, Any] | None:
        """Fetch one country by id."""
        result = await call_json_function("fn_geo", 4, {"country_id": country_id})
        return row_from_jsonb(result)

    async def get_state(self, state_id: int) -> dict[str, Any] | None:
        """Fetch one state by id."""
        result = await call_json_function("fn_geo", 5, {"state_id": state_id})
        return row_from_jsonb(result)

    async def get_city(self, city_id: int) -> dict[str, Any] | None:
        """Fetch one city by id."""
        result = await call_json_function("fn_geo", 6, {"city_id": city_id})
        return row_from_jsonb(result)
