"""FastAPI application factory for PariPath v1."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from v1.core.settings import settings
from v1.database.connection import close_db, init_db
from v1.middleware import setup_middleware
from v1.routers import auth, health, internal, users
from v1.services.auth.jwks import jwks_refresh_manager
from v1.utils.logger import setup_logger
from v1.utils.redis_cache import auth_redis_cache


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize and close process-level resources."""
    setup_logger(
        settings.logging.file,
        settings.logging.level,
        json_logs=settings.logging.json_logs,
    )
    if not settings.app.skip_startup_integrations:
        await init_db()
        jwks_refresh_manager.start()
    try:
        yield
    finally:
        await jwks_refresh_manager.stop()
        await auth_redis_cache.close()
        if not settings.app.skip_startup_integrations:
            await close_db()


def create_app() -> FastAPI:
    """Create a configured FastAPI app."""
    api = FastAPI(
        title=settings.app.name,
        version=settings.app.version,
        debug=settings.app.debug,
        lifespan=lifespan,
    )
    setup_middleware(api)
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(internal.router)
    return api


app = create_app()
