"""Lazy Typesense SDK clients."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import typesense

from core.config.settings import settings


def _client_config() -> dict[str, Any]:
    """Build Typesense client configuration from settings."""
    return {
        "api_key": settings.typesense.api_key_value,
        "nodes": [
            {
                "host": settings.typesense.host,
                "port": str(settings.typesense.port),
                "protocol": settings.typesense.protocol,
            }
        ],
        "connection_timeout_seconds": 5,
    }


@lru_cache(maxsize=1)
def get_typesense_client() -> typesense.Client:
    """Return a process-wide synchronous Typesense client."""
    return typesense.Client(_client_config())


@lru_cache(maxsize=1)
def get_typesense_async_client() -> typesense.AsyncClient:
    """Return a process-wide asynchronous Typesense client."""
    return typesense.AsyncClient(_client_config())
