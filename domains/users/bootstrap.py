"""Users domain use cases."""

from __future__ import annotations

from core.logging.logger import get_logger
from domains.users.repository import UserRepository
from domains.users.user import BootstrapUserCommand, User

logger = get_logger(__name__)


class BootstrapUser:
    """Create or return the local user for an authenticated identity subject."""

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(
        self,
        command: BootstrapUserCommand,
        *,
        request_id: str | None = None,
    ) -> User:
        """Run the bootstrap user use case."""
        logger.info(
            "user_bootstrap_received request_id={} keycloak_sub={}",
            request_id,
            command.keycloak_sub[:8] if command.keycloak_sub else None,
        )
        existing = await self._users.get_by_keycloak_sub(command.keycloak_sub)
        user = await self._users.bootstrap(command)
        logger.info(
            "user_bootstrap_committed request_id={} user_id={} created={}",
            request_id,
            user.id,
            existing is None,
        )
        return user
