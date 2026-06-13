"""Explorers index settings — must match filter/sort usage in search."""

from __future__ import annotations

from meilisearch import Client

EXPLORER_FILTERABLE = [
    "destination_country",
    "current_country",
    "destination_city",
    "availability",
    "visibility",
    "trip_starts_at",
    "trip_ends_at",
    "_geo",
]

EXPLORER_SORTABLE = [
    "last_active_at",
    "trip_starts_at",
    "trip_ends_at",
    "_geo",
]

EXPLORER_SEARCHABLE = [
    "display_name",
    "headline",
    "search_text",
    "languages",
]


def ensure_explorer_index_settings(client: Client, index_uid: str) -> None:
    """Apply index settings; triggers re-index when filterable/sortable change."""
    index = client.index(index_uid)
    index.update_filterable_attributes(EXPLORER_FILTERABLE)
    index.update_sortable_attributes(EXPLORER_SORTABLE)
    index.update_searchable_attributes(EXPLORER_SEARCHABLE)
