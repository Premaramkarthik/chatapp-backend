"""Users domain use cases."""

from __future__ import annotations

from domains.users.repository import UserRepository
from domains.users.user import BootstrapUserCommand, User


class BootstrapUser:
    """Create or return the local user for an authenticated identity subject."""

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, command: BootstrapUserCommand) -> User:
        """Run the bootstrap user use case."""
        return await self._users.bootstrap(command)
