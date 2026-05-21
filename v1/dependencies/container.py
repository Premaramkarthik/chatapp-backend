"""HTTP dependency factories for use cases and adapters."""

from __future__ import annotations

from v1.database.repositories import PostgresUserRepository
from v1.services.auth import AuthService
from v1.services.users.bootstrap_user import BootstrapUser


async def get_bootstrap_user_use_case() -> BootstrapUser:
    """Build the bootstrap user use case for a request."""
    return BootstrapUser(users=PostgresUserRepository())


async def get_auth_service() -> AuthService:
    """Build the auth service for a request."""
    return AuthService()
