"""Lazy Meilisearch SDK client."""

from __future__ import annotations

from functools import lru_cache

from meilisearch import Client

from core.config.settings import settings


@lru_cache(maxsize=1)
def get_meilisearch_client() -> Client:
    """Return a process-wide Meilisearch client."""
    return Client(
        settings.meilisearch.url.rstrip("/"),
        settings.meilisearch.master_key_value,
    )
