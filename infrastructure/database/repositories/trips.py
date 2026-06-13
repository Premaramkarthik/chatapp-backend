"""Travel plan and location repositories."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresTripRepository:
    """Postgres access for travel plans and current location."""

    async def create_travel_plan(
        self,
        user_id: str,
        *,
        title: str | None,
        start_date: Any | None,
        end_date: Any | None,
        is_primary: bool,
        destinations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a travel plan with ordered destinations."""

        def _date_value(value: Any) -> Any:
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return value

        payload: dict[str, Any] = {
            "user_id": user_id,
            "title": title,
            "start_date": _date_value(start_date),
            "end_date": _date_value(end_date),
            "is_primary": is_primary,
            "destinations": destinations,
        }
        result = await call_json_function("fn_travel_plans", 2, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_travel_plans mode 2 returned no row")
        return row

    async def list_travel_plans(self, user_id: str) -> list[dict[str, Any]]:
        """List travel plans for a user."""
        result = await call_json_function("fn_travel_plans", 1, {"user_id": user_id})
        return list_from_jsonb(result)

    async def upsert_current_location(
        self,
        user_id: str,
        *,
        country_id: int | None,
        state_id: int | None,
        city_id: int | None,
        custom_country_name: str | None,
        custom_state_name: str | None,
        custom_city_name: str | None,
        latitude: float | None,
        longitude: float | None,
        source: str = "manual",
    ) -> dict[str, Any]:
        """Update traveler current location."""
        payload: dict[str, Any] = {
            "user_id": user_id,
            "country_id": country_id,
            "state_id": state_id,
            "city_id": city_id,
            "custom_country_name": custom_country_name,
            "custom_state_name": custom_state_name,
            "custom_city_name": custom_city_name,
            "latitude": latitude,
            "longitude": longitude,
            "source": source,
        }
        result = await call_json_function("fn_traveler_current_locations", 2, payload)
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_traveler_current_locations mode 2 returned no row")
        return row
