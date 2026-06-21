"""Users domain use cases."""

from __future__ import annotations

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
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
        log_info(
            logger,
            "User bootstrap request received",
            request_id=request_id,
            keycloak_sub=command.keycloak_sub[:8] if command.keycloak_sub else None,
        )
        existing = await self._users.get_by_keycloak_sub(command.keycloak_sub)
        user = await self._users.bootstrap(command)
        log_info(
            logger,
            "User bootstrap committed",
            request_id=request_id,
            user_id=user.id,
            created=existing is None,
        )
        if settings.matrix.enabled:
            from domains.matrix.provisioning.service import (
                MatrixProvisionError,
                matrix_provisioning_service,
            )

            try:
                await matrix_provisioning_service.ensure_user_provisioned(
                    user_id=user.id,
                    display_name=user.display_name or user.email,
                    request_id=request_id,
                )
            except MatrixProvisionError as exc:
                log_warning(
                    logger,
                    "Matrix user provision skipped during bootstrap",
                    matrix_category="provisioning",
                    request_id=request_id,
                    user_id=user.id,
                    reason=str(exc),
                )
        return user
