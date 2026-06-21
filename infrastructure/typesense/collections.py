"""Typesense collection schema definitions."""

from __future__ import annotations

from typing import Any

from core.config.settings import settings
from infrastructure.typesense.client import get_typesense_client


def _users_schema(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "username", "type": "string"},
            {"name": "full_name", "type": "string"},
            {"name": "profile_photo", "type": "string", "optional": True},
            {"name": "role", "type": "string", "facet": True, "optional": True},
            {"name": "city", "type": "string", "optional": True},
            {"name": "country", "type": "string", "optional": True},
            {"name": "verified", "type": "bool", "facet": True},
            {"name": "created_at", "type": "int64", "optional": True},
            {"name": "profile_completed", "type": "bool", "facet": True},
            {"name": "connections_count", "type": "int32"},
            {"name": "recent_activity_at", "type": "int64", "optional": True},
            {"name": "search_popularity", "type": "float"},
            {"name": "is_searchable", "type": "bool", "facet": True},
        ],
        "default_sorting_field": "connections_count",
    }


def _travelers_schema(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "user_id", "type": "string"},
            {"name": "from_city", "type": "string", "optional": True},
            {"name": "to_city", "type": "string", "optional": True},
            {"name": "from_country", "type": "string", "facet": True, "optional": True},
            {"name": "to_country", "type": "string", "facet": True, "optional": True},
            {"name": "departure_date", "type": "int64", "optional": True},
            {"name": "verified", "type": "bool", "facet": True},
            {"name": "has_upcoming_trip", "type": "bool", "facet": True},
            {"name": "profile_completed", "type": "bool", "facet": True},
            {"name": "recent_activity_at", "type": "int64"},
            {"name": "is_searchable", "type": "bool", "facet": True},
        ],
        "default_sorting_field": "recent_activity_at",
    }


def _cities_schema(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "city_name", "type": "string"},
            {"name": "state_name", "type": "string", "optional": True},
            {"name": "country_name", "type": "string", "optional": True},
            {"name": "country_iso2", "type": "string", "facet": True, "optional": True},
        ],
    }


def _countries_schema(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "country_name", "type": "string"},
            {"name": "iso2", "type": "string", "facet": True, "optional": True},
        ],
    }


def _states_schema(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "state_name", "type": "string"},
            {"name": "country_name", "type": "string", "optional": True},
            {"name": "country_iso2", "type": "string", "facet": True, "optional": True},
        ],
    }


def _user_recommendations_schema(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "user_id", "type": "string", "facet": True},
            {"name": "recommended_user_id", "type": "string"},
            {"name": "score", "type": "float"},
            {"name": "reason", "type": "string", "optional": True},
        ],
        "default_sorting_field": "score",
    }


def _popular_searches_schema(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "label", "type": "string"},
            {"name": "kind", "type": "string", "facet": True},
            {"name": "score", "type": "float"},
            {"name": "updated_at", "type": "int64", "optional": True},
        ],
        "default_sorting_field": "score",
    }


def collection_schemas() -> dict[str, dict[str, Any]]:
    """Return all collection schemas keyed by logical name."""
    ts = settings.typesense
    return {
        "users": _users_schema(ts.users_collection),
        "travelers": _travelers_schema(ts.travelers_collection),
        "cities": _cities_schema(ts.cities_collection),
        "countries": _countries_schema(ts.countries_collection),
        "states": _states_schema(ts.states_collection),
        "user_recommendations": _user_recommendations_schema(ts.user_recommendations_collection),
        "popular_searches": _popular_searches_schema(ts.popular_searches_collection),
    }


def ensure_all_collections() -> None:
    """Create missing Typesense collections idempotently."""
    client = get_typesense_client()
    existing = {item["name"] for item in client.collections.retrieve()}
    for schema in collection_schemas().values():
        if schema["name"] not in existing:
            client.collections.create(schema)
