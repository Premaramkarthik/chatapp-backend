"""Users domain repository ports."""

from __future__ import annotations

from typing import Protocol

from v1.models.user import BootstrapUserCommand, User


class UserRepository(Protocol):
    """Persistence operations required by users domain use cases."""

    async def bootstrap(self, command: BootstrapUserCommand) -> User:
        """Create or return a user for an identity subject."""
        ...

    async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
        """Return a user by external identity subject."""
        ...
