"""Display helpers for location fields."""

from __future__ import annotations

from typing import Any

from infrastructure.database.repositories.geo import PostgresGeoRepository


async def enrich_home_location(row: dict[str, Any]) -> dict[str, str | None]:
    """Resolve display names using custom_* priority over master geo names."""
    geo = PostgresGeoRepository()
    display_country = row.get("custom_home_country_name")
    if not display_country and row.get("home_country_id"):
        country = await geo.get_country(int(row["home_country_id"]))
        display_country = country["name"] if country else None

    display_state = row.get("custom_home_state_name")
    if not display_state and row.get("home_state_id"):
        state = await geo.get_state(int(row["home_state_id"]))
        display_state = state["name"] if state else None

    display_city = row.get("custom_home_city_name")
    if not display_city and row.get("home_city_id"):
        city = await geo.get_city(int(row["home_city_id"]))
        display_city = city["name"] if city else None

    return {
        "display_home_country": display_country,
        "display_home_state": display_state,
        "display_home_city": display_city,
    }
