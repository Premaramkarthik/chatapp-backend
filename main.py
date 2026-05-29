"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config.settings import settings
from core.logging.logger import setup_logger
from domains.auth.jwks import jwks_refresh_manager
from infrastructure.database.connection import close_db, init_db
from infrastructure.redis.cache import auth_redis_cache
from v1.middleware import setup_middleware
from v1.routers import auth, health, internal, users


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
