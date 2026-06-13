"""Map discovery snapshots to Meilisearch documents."""

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


def snapshot_to_meili_document(row: dict[str, Any]) -> dict[str, Any]:
    """Build a Meilisearch document from a discovery snapshot row."""
    languages = row.get("languages") or []
    interests = row.get("interests") or []
    search_bits = [
        row.get("display_name"),
        row.get("headline"),
        row.get("destination_city_name"),
        *languages,
        *interests,
    ]
    search_text = " ".join(part for part in search_bits if part)

    doc: dict[str, Any] = {
        "id": str(row["user_id"]),
        "display_name": row.get("display_name"),
        "headline": row.get("headline"),
        "avatar_url": row.get("avatar_url"),
        "destination_country": row.get("destination_country_iso"),
        "current_country": row.get("current_country_iso"),
        "destination_city": (
            str(row["destination_city_id"]) if row.get("destination_city_id") is not None else None
        ),
        "destination_city_name": row.get("destination_city_name"),
        "availability": row.get("connection_availability"),
        "visibility": row.get("visibility"),
        "languages": languages,
        "search_text": search_text,
        "last_active_at": _to_unix(row.get("last_active_at")),
        "trip_starts_at": _date_to_unix(row.get("trip_start_date")),
        "trip_ends_at": _date_to_unix(row.get("trip_end_date")),
    }
    lat, lng = row.get("geo_lat"), row.get("geo_lng")
    if lat is not None and lng is not None:
        doc["_geo"] = {"lat": float(lat), "lng": float(lng)}
    return doc


def should_index_snapshot(row: dict[str, Any]) -> bool:
    """Return True when the traveler should appear in Meilisearch."""
    return bool(row.get("is_discoverable")) and row.get("visibility") == "discoverable"
