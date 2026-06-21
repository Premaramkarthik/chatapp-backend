"""Typesense health check."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from core.config.settings import settings


@dataclass
class TypesenseHealth:
    """Typesense health check result."""

    ok: bool
    detail: str


async def health() -> TypesenseHealth:
    """Check Typesense /health endpoint."""
    if not settings.typesense.enabled:
        return TypesenseHealth(ok=True, detail="disabled")

    url = (
        f"{settings.typesense.protocol}://{settings.typesense.host}:"
        f"{settings.typesense.port}/health"
    )
    headers = {"X-TYPESENSE-API-KEY": settings.typesense.api_key_value}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        return TypesenseHealth(ok=False, detail=f"{type(exc).__name__}: {exc}")
    return TypesenseHealth(ok=True, detail="ok")
