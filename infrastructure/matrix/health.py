"""Matrix Synapse health check."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from core.config.settings import settings
from infrastructure.matrix.admin import synapse_admin_client


@dataclass(frozen=True)
class MatrixHealthResult:
    """Health probe result for Matrix Synapse."""

    ok: bool
    detail: str


async def matrix_health() -> MatrixHealthResult:
    """Check Synapse client API availability."""
    if not settings.matrix.enabled:
        return MatrixHealthResult(ok=True, detail="disabled")
    url = f"{settings.matrix.homeserver_url.rstrip('/')}/_matrix/client/versions"
    try:
        async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return MatrixHealthResult(ok=True, detail="ok")
            return MatrixHealthResult(ok=False, detail=f"status={response.status_code}")
    except Exception as exc:
        return MatrixHealthResult(ok=False, detail=f"{type(exc).__name__}: {exc}")


async def matrix_admin_health() -> MatrixHealthResult:
    """Check Synapse Admin API access via service admin credentials."""
    if not settings.matrix.enabled:
        return MatrixHealthResult(ok=True, detail="disabled")
    try:
        await synapse_admin_client.get_token()
        await synapse_admin_client.verify_admin_access()
        return MatrixHealthResult(ok=True, detail="ok")
    except Exception as exc:
        return MatrixHealthResult(ok=False, detail=f"{type(exc).__name__}: {exc}")
