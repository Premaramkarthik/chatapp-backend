"""HTTP dependency factories for use cases and adapters."""

from __future__ import annotations

from domains.auth import AuthService
from domains.users.bootstrap import BootstrapUser
from infrastructure.database.repositories import PostgresUserRepository


async def get_bootstrap_user_use_case() -> BootstrapUser:
    """Build the bootstrap user use case for a request."""
    return BootstrapUser(users=PostgresUserRepository())


async def get_auth_service() -> AuthService:
    """Build the auth service for a request."""
    return AuthService()
