"""Database request lifecycle middleware."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from v1.core.settings import settings
from v1.database.connection import get_pool
from v1.middleware.state import DB_CONNECTION_STATE_KEY, ensure_state


class DatabaseSessionMiddleware:
    """Acquire one asyncpg connection for request-scoped DB work."""

    def __init__(self, app: ASGIApp, *, excluded_paths: set[str]) -> None:
        self.app = app
        self.excluded_paths = excluded_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or settings.app.skip_startup_integrations
            or scope["path"] in self.excluded_paths
        ):
            await self.app(scope, receive, send)
            return

        pool = await get_pool()
        async with pool.acquire() as connection:
            state = ensure_state(scope)
            state[DB_CONNECTION_STATE_KEY] = connection
            try:
                await self.app(scope, receive, send)
            finally:
                state.pop(DB_CONNECTION_STATE_KEY, None)
