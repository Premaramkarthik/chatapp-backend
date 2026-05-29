"""CORS middleware registration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config.settings import settings


def add_cors_middleware(app: FastAPI) -> None:
    """Register CORS middleware from environment-backed settings."""
    if not settings.middleware.cors_enabled:
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.middleware.cors_origins,
        allow_credentials=settings.middleware.cors_allow_credentials,
        allow_methods=settings.middleware.cors_allow_methods,
        allow_headers=settings.middleware.cors_allow_headers,
    )
