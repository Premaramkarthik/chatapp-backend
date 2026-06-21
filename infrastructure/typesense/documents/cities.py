"""Map geo city rows to Typesense documents."""

from __future__ import annotations

from typing import Any


def city_row_to_document(row: dict[str, Any]) -> dict[str, Any]:
    """Build a Typesense city document."""
    return {
        "id": str(row["id"]),
        "city_name": row.get("name") or row.get("city_name"),
        "state_name": row.get("state_name"),
        "country_name": row.get("country_name"),
        "country_iso2": row.get("country_iso2") or row.get("iso2"),
    }
