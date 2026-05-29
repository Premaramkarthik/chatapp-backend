"""Helpers for mode-based JSONB stored function results."""

from __future__ import annotations

import json
from typing import Any


def row_from_jsonb(result: Any) -> dict[str, Any] | None:
    """Convert a single JSONB function result to a dict."""
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        parsed = json.loads(result)
        return None if parsed is None else dict(parsed)
    return dict(result)


def list_from_jsonb(result: Any) -> list[dict[str, Any]]:
    """Convert a JSONB array function result to a list of dicts."""
    if result is None:
        return []
    if isinstance(result, list):
        return [dict(item) for item in result]
    if isinstance(result, str):
        parsed = json.loads(result)
        if not parsed:
            return []
        return [dict(item) for item in parsed]
    return [dict(item) for item in result]


def map_social_db_error(exc: Exception) -> None:
    """Map PostgreSQL RAISE EXCEPTION messages to repository ValueErrors."""
    message = str(exc).lower()
    if "blocked" in message:
        raise ValueError("blocked") from exc
    if "not_found" in message:
        raise ValueError("not_found") from exc
    if "forbidden" in message:
        raise ValueError("forbidden") from exc
    if "invalid_status" in message:
        raise ValueError("invalid_status") from exc
    raise exc
