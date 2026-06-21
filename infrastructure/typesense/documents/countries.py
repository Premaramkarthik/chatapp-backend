"""Map geo country rows to Typesense documents."""

from __future__ import annotations

from typing import Any


def country_row_to_document(row: dict[str, Any]) -> dict[str, Any]:
    """Build a Typesense country document."""
    return {
        "id": str(row["id"]),
        "country_name": row.get("name") or row.get("country_name"),
        "iso2": row.get("iso2"),
    }
