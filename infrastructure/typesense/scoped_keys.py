"""Scoped Typesense API key generation (future direct-client reads)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from infrastructure.typesense.client import get_typesense_client


def generate_scoped_search_key(
    *,
    collections: list[str],
    filter_by: str | None = None,
    expires_at: datetime | None = None,
) -> str:
    """Generate a scoped search-only API key stub for future mobile clients."""
    params: dict[str, Any] = {
        "description": "scoped search key",
        "actions": ["documents:search"],
        "collections": collections,
    }
    if filter_by:
        params["filter_by"] = filter_by
    if expires_at is not None:
        params["expires_at"] = int(expires_at.timestamp())
    client = get_typesense_client()
    return str(client.keys.create(params))
