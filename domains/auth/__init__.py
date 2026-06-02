"""Authentication service exports."""

from domains.auth.models import AuthSession, AuthSessionStatus
from domains.auth.service import AuthService

__all__ = [
    "AuthService",
    "AuthSession",
    "AuthSessionResolver",
    "AuthSessionStatus",
    "auth_service",
    "auth_session_resolver",
]


def __getattr__(name: str):
    """Lazy imports for resolver singletons."""
    if name == "auth_service":
        from domains.auth.service import auth_service

        return auth_service
    if name == "AuthSessionResolver":
        from domains.auth.session_resolver import AuthSessionResolver

        return AuthSessionResolver
    if name == "auth_session_resolver":
        from domains.auth.session_resolver import auth_session_resolver

        return auth_session_resolver
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
