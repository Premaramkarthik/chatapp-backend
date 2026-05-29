"""Travelers index settings — must match filter/sort usage in search."""

from __future__ import annotations

from meilisearch import Client

TRAVELER_FILTERABLE = [
    "destination_country",
    "current_country",
    "destination_city",
    "availability",
    "visibility",
    "trip_starts_at",
    "trip_ends_at",
    "_geo",
]

TRAVELER_SORTABLE = [
    "last_active_at",
    "trip_starts_at",
    "trip_ends_at",
    "_geo",
]

TRAVELER_SEARCHABLE = [
    "display_name",
    "headline",
    "search_text",
    "languages",
]


def ensure_traveler_index_settings(client: Client, index_uid: str) -> None:
    """Apply index settings; triggers re-index when filterable/sortable change."""
    index = client.index(index_uid)
    index.update_filterable_attributes(TRAVELER_FILTERABLE)
    index.update_sortable_attributes(TRAVELER_SORTABLE)
    index.update_searchable_attributes(TRAVELER_SEARCHABLE)
