"""Map discovery snapshots to Typesense traveler documents."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _to_unix(value: datetime | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        return None
    return int(value.timestamp())


def _date_to_unix(value: date | None) -> int | None:
    if value is None:
        return None
    return int(datetime.combine(value, datetime.min.time()).timestamp())


def should_index_traveler_snapshot(row: dict[str, Any]) -> bool:
    """Return True when the traveler should appear in Typesense."""
    return bool(row.get("is_discoverable")) and row.get("visibility") == "discoverable"


def snapshot_to_traveler_document(
    row: dict[str, Any],
    *,
    email_verified: bool = False,
    profile_completed: bool = False,
) -> dict[str, Any]:
    """Build a Typesense traveler document from a discovery snapshot row."""
    today = date.today()
    trip_start = row.get("trip_start_date")
    has_upcoming = bool(trip_start and trip_start >= today)
    doc: dict[str, Any] = {
        "id": str(row["user_id"]),
        "user_id": str(row["user_id"]),
        "from_city": row.get("current_city_name"),
        "to_city": row.get("destination_city_name"),
        "from_country": row.get("current_country_iso"),
        "to_country": row.get("destination_country_iso"),
        "departure_date": _date_to_unix(trip_start),
        "verified": email_verified,
        "has_upcoming_trip": has_upcoming,
        "profile_completed": profile_completed,
        "recent_activity_at": _to_unix(row.get("last_active_at")) or 0,
        "is_searchable": should_index_traveler_snapshot(row),
    }
    return doc
