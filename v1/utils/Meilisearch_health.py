"""Meilisearch health and index configuration helpers."""

from dataclasses import dataclass

import httpx

from v1.core.settings import settings


@dataclass
class MeilisearchHealth:
    """Meilisearch health check result."""

    ok: bool
    detail: str


async def health() -> MeilisearchHealth:
    """Check Meilisearch health endpoint."""
    if not settings.meilisearch.enabled:
        return MeilisearchHealth(ok=True, detail="disabled")

    headers = {"Authorization": f"Bearer {settings.meilisearch.master_key_value}"}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{settings.meilisearch.url.rstrip('/')}/health",
                headers=headers,
            )
            response.raise_for_status()
    except Exception as exc:
        return MeilisearchHealth(ok=False, detail=f"{type(exc).__name__}: {exc}")
    return MeilisearchHealth(ok=True, detail="ok")
