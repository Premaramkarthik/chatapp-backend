"""PostgreSQL users repository adapter."""

from __future__ import annotations

from v1.database.connection import call_json_function
from v1.models.user import BootstrapUserCommand, User
from v1.services.users.user_repository import UserRepository


class PostgresUserRepository(UserRepository):
    """PostgreSQL adapter for users domain persistence."""

    async def bootstrap(self, command: BootstrapUserCommand) -> User:
        """Create or return the local user row for an authenticated principal."""
        row = await call_json_function(
            "fn_users",
            1,
            {
                "keycloak_sub": command.keycloak_sub,
                "email": command.email,
                "display_name": command.display_name,
            },
        )
        return User.from_mapping(row)

    async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
        """Return a local user by Keycloak subject."""
        row = await call_json_function("fn_users", 3, {"keycloak_sub": keycloak_sub})
        return None if row is None else User.from_mapping(row)
