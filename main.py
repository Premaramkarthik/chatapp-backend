"""FastAPI application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config.settings import settings
from core.logging.logger import setup_logger
from core.observability.setup import init_observability
from domains.auth.jwks import jwks_refresh_manager
from domains.auth.verification_reconcile import run_verification_reconcile_loop
from infrastructure.database.connection import close_db, init_db
from infrastructure.keycloak.google_idp_config import (
    ensure_keycloak_google_idp,
    ensure_keycloak_web_client,
)
from infrastructure.keycloak.realm_bootstrap import ensure_keycloak_realm
from infrastructure.keycloak.smtp_config import ensure_keycloak_smtp
from infrastructure.keycloak.startup_validation import validate_keycloak_startup
from infrastructure.redis.cache import auth_redis_cache
from infrastructure.typesense.collections import ensure_all_collections
from v1.middleware import setup_middleware
from v1.routers import (
    auth,
    blocks,
    chat,
    connections,
    connectors,
    explorers,
    geo,
    health,
    notifications,
    reports,
    search,
    users,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize and close process-level resources."""
    reconcile_stop = asyncio.Event()
    reconcile_task: asyncio.Task[None] | None = None
    if not settings.app.skip_startup_integrations:
        await init_db()
        if settings.keycloak.enabled:
            await ensure_keycloak_realm()
            await ensure_keycloak_smtp()
            await ensure_keycloak_web_client()
            await ensure_keycloak_google_idp()
            await validate_keycloak_startup()
        jwks_refresh_manager.start()
        if settings.typesense.enabled:
            await asyncio.to_thread(ensure_all_collections)
        if settings.auth.verification_reconcile_enabled:
            reconcile_task = asyncio.create_task(
                run_verification_reconcile_loop(reconcile_stop),
            )
    try:
        yield
    finally:
        reconcile_stop.set()
        if reconcile_task is not None:
            reconcile_task.cancel()
            try:
                await reconcile_task
            except asyncio.CancelledError:
                pass
        await jwks_refresh_manager.stop()
        await auth_redis_cache.close()
        if not settings.app.skip_startup_integrations:
            await close_db()


def create_app() -> FastAPI:
    """Create a configured FastAPI app."""
    setup_logger(settings.logging.file, settings.logging.level)
    api = FastAPI(
        title=settings.app.name,
        version=settings.app.version,
        debug=settings.app.debug,
        lifespan=lifespan,
    )
    init_observability(api)
    setup_middleware(api)
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(explorers.router)
    api.include_router(connectors.router)
    api.include_router(connections.router)
    api.include_router(blocks.router)
    api.include_router(reports.router)
    api.include_router(notifications.router)
    api.include_router(chat.router)
    api.include_router(geo.router)
    api.include_router(search.router)
    return api


app = create_app()
