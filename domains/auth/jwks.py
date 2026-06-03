"""Background JWKS refresh management."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from core.config.settings import settings
from core.observability.prometheus_metrics import AUTH_JWKS_REFRESH_FAILURE_TOTAL
from infrastructure.keycloak.adapter import keycloak_verifier


class JwksRefreshManager:
    """Refresh Keycloak JWKS in the background to smooth key rotation."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start background refresh loop if enabled."""
        if not settings.keycloak.enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop background refresh loop."""
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await keycloak_verifier.refresh_jwks()
            except Exception:
                AUTH_JWKS_REFRESH_FAILURE_TOTAL.inc()
            await asyncio.sleep(settings.keycloak.jwks_refresh_interval_sec)


jwks_refresh_manager = JwksRefreshManager()
