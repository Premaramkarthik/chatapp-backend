"""Shared HTTP request context helpers."""

from __future__ import annotations

from starlette.requests import Request


def request_id_from(request: Request) -> str | None:
    """Return the correlation request id attached by middleware."""
    return getattr(request.state, "request_id", None)
