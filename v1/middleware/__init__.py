"""HTTP middleware stack registration."""

from fastapi import FastAPI

from core.config.settings import settings
from v1.middleware.authentication import JWTAuthenticationMiddleware
from v1.middleware.cors import add_cors_middleware
from v1.middleware.database import DatabaseSessionMiddleware
from v1.middleware.error_handling import ErrorHandlingMiddleware
from v1.middleware.logging import RequestResponseLoggingMiddleware
from v1.middleware.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitMiddleware,
    RedisRateLimitStore,
)
from v1.middleware.request_id import RequestIdMiddleware
from v1.middleware.security import CSRFMiddleware, SecurityHeadersMiddleware


def setup_middleware(app: FastAPI) -> None:
    """Register middleware in production request execution order.

    Starlette wraps middleware so the last added middleware runs first on the
    request path. Register from innermost to outermost to make the intended
    order explicit.
    """
    if settings.middleware.auth_enabled:
        app.add_middleware(
            JWTAuthenticationMiddleware,
            protected_prefixes=settings.middleware.auth_protected_prefixes,
            public_paths=settings.middleware.auth_public_paths,
            public_prefixes=settings.middleware.auth_public_prefixes,
        )

    if settings.middleware.csrf_enabled:
        app.add_middleware(
            CSRFMiddleware,
            excluded_paths=settings.middleware.csrf_excluded_paths,
        )

    if settings.middleware.db_session_enabled:
        app.add_middleware(
            DatabaseSessionMiddleware,
            excluded_paths=settings.middleware.db_session_excluded_paths,
        )

    if settings.middleware.rate_limit_enabled:
        rate_limit_store = (
            RedisRateLimitStore() if settings.redis.enabled else InMemoryRateLimitStore()
        )
        app.add_middleware(
            RateLimitMiddleware,
            store=rate_limit_store,
            limit=settings.middleware.rate_limit_requests,
            window_sec=settings.middleware.rate_limit_window_sec,
            excluded_paths=settings.middleware.rate_limit_excluded_paths,
        )

    app.add_middleware(
        RequestResponseLoggingMiddleware,
        log_request_body=settings.middleware.log_request_body,
    )
    app.add_middleware(ErrorHandlingMiddleware)
    add_cors_middleware(app)
    if settings.middleware.security_headers_enabled:
        app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RequestIdMiddleware,
        header_name=settings.middleware.request_id_header,
    )
