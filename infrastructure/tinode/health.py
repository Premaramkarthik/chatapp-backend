"""Tinode server reachability checks."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from core.config.settings import settings


@dataclass
class TinodeHealth:
    """Tinode health check result."""

    ok: bool
    detail: str


async def health() -> TinodeHealth:
    """Probe Tinode HTTP endpoint when integration is enabled."""
    if not settings.tinode.enabled:
        return TinodeHealth(ok=True, detail="disabled")

    base = settings.tinode.web_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{base}/")
            if response.status_code >= 500:
                return TinodeHealth(
                    ok=False,
                    detail=f"HTTP {response.status_code}",
                )
    except Exception as exc:
        return TinodeHealth(ok=False, detail=f"{type(exc).__name__}: {exc}")
    return TinodeHealth(ok=True, detail="ok")
