"""Map popular search aggregates to Typesense documents."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def popular_search_row_to_document(row: dict[str, Any]) -> dict[str, Any]:
    """Build a Typesense popular_searches document."""
    updated_at = row.get("updated_at")
    unix = int(updated_at.timestamp()) if isinstance(updated_at, datetime) else None
    return {
        "id": str(row["id"]),
        "label": row["label"],
        "kind": row.get("kind") or "query",
        "score": float(row.get("score") or 0),
        "updated_at": unix,
    }
