"""Messenger traveler search via Meilisearch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from meilisearch import Client


@dataclass(frozen=True)
class TravelerSearchQuery:
    """Parameters for destination-country-first traveler search."""

    destination_country: str
    q: str = ""
    city_id: str | None = None
    current_country: str | None = None
    trip_active_on: date | None = None
    limit: int = 20
    offset: int = 0
    sort: list[str] | None = None


def build_filter(query: TravelerSearchQuery) -> str:
    """Build a Meilisearch filter string (all fields must be filterable)."""
    parts = [
        f'destination_country = "{query.destination_country.upper()}"',
        'visibility = "discoverable"',
        'availability != "unavailable"',
    ]
    if query.city_id:
        parts.append(f'destination_city = "{query.city_id}"')
    if query.current_country:
        parts.append(f'current_country = "{query.current_country.upper()}"')
    if query.trip_active_on:
        ts = int(datetime.combine(query.trip_active_on, datetime.min.time()).timestamp())
        parts.append(f"trip_ends_at >= {ts}")
    return " AND ".join(parts)


def search_travelers(
    client: Client,
    index_uid: str,
    query: TravelerSearchQuery,
) -> dict:
    """Run a Meilisearch search against the travelers index."""
    params: dict = {
        "filter": build_filter(query),
        "limit": query.limit,
        "offset": query.offset,
    }
    if query.sort:
        params["sort"] = query.sort
    else:
        params["sort"] = ["last_active_at:desc"]
    return client.index(index_uid).search(query.q, params)
