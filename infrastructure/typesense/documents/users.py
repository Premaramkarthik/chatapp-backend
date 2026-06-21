"""Map user rows to Typesense user documents."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def _slugify_username(display_name: str | None) -> str:
    """Derive a search username slug from display_name."""
    if not display_name:
        return ""
    slug = re.sub(r"[^a-zA-Z0-9]+", "", display_name.lower())
    return slug[:64]


def _to_unix(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(value.timestamp())


def user_row_to_document(row: dict[str, Any]) -> dict[str, Any]:
    """Build a Typesense user document from a Postgres user search row."""
    display_name = row.get("display_name")
    status = row.get("status") or "active"
    visibility = row.get("visibility") or "discoverable"
    allow_search = row.get("allow_search_discovery", True)
    is_searchable = status == "active" and visibility == "discoverable" and bool(allow_search)
    recent_candidates = [
        row.get("recent_activity_at"),
        row.get("profile_updated_at"),
        row.get("updated_at"),
    ]
    recent_activity_at = None
    for candidate in recent_candidates:
        unix = _to_unix(candidate)
        if unix is not None:
            recent_activity_at = max(recent_activity_at or 0, unix)
    return {
        "id": str(row["id"]),
        "username": _slugify_username(display_name),
        "full_name": display_name,
        "profile_photo": row.get("avatar_url"),
        "role": row.get("account_mode"),
        "city": row.get("home_city_name") or row.get("custom_home_city_name"),
        "country": row.get("home_country_name") or row.get("custom_home_country_name"),
        "verified": bool(row.get("email_verified")),
        "created_at": _to_unix(row.get("created_at")),
        "profile_completed": bool(row.get("onboarding_completed_at")),
        "connections_count": int(row.get("connections_count") or 0),
        "recent_activity_at": recent_activity_at,
        "search_popularity": float(row.get("search_popularity") or 0),
        "is_searchable": is_searchable,
    }
