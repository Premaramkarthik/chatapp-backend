"""Matrix user provisioning."""

from __future__ import annotations

from typing import Any

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
from infrastructure.database.repositories.matrix_users import PostgresMatrixUserRepository
from infrastructure.matrix.admin import synapse_admin_client
from v1.utils.base import MatrixIntegrationError

logger = get_logger(__name__)


class MatrixProvisionError(RuntimeError):
    """Matrix user cannot be provisioned."""


def matrix_localpart_for_user(user_id: str) -> str:
    """Return a stable Matrix localpart for a local user id."""
    return f"u{user_id.replace('-', '')}"


def matrix_mxid_for_localpart(localpart: str) -> str:
    """Build a fully qualified Matrix user id."""
    return f"@{localpart}:{settings.matrix.server_name}"


class MatrixProvisioningService:
    """Provision Matrix accounts and persist encrypted credentials."""

    def __init__(
        self,
        *,
        users: PostgresMatrixUserRepository | None = None,
    ) -> None:
        self._users = users or PostgresMatrixUserRepository()

    async def ensure_user_provisioned(
        self,
        *,
        user_id: str,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or return a Matrix user mapping for a local user."""
        if not settings.matrix.enabled:
            raise MatrixProvisionError("Matrix is disabled")

        existing = await self._users.get_by_user_id(user_id)

        from infrastructure.database.repositories.users import PostgresUserRepository

        user = await PostgresUserRepository().get_by_id(user_id)
        subject = user.keycloak_sub if user else None
        if not subject:
            raise MatrixProvisionError("Verified application identity required")
        localpart = existing["localpart"] if existing else matrix_localpart_for_user(user_id)
        mxid = existing["mxid"] if existing else matrix_mxid_for_localpart(localpart)
        if not mxid.endswith(f":{settings.matrix.server_name}"):
            raise MatrixProvisionError("Provider migration requires an explicit migration")

        log_info(
            logger,
            "Matrix user provision request received",
            matrix_category="provisioning",
            request_id=request_id,
            user_id=user_id,
            mxid=mxid,
        )
        try:
            await synapse_admin_client.create_or_update_user(
                mxid=mxid,
                subject=subject,
                displayname=display_name,
            )
        except MatrixIntegrationError as exc:
            log_warning(
                logger,
                "Matrix user provision failed",
                matrix_category="provisioning",
                request_id=request_id,
                user_id=user_id,
                reason=type(exc).__name__,
            )
            raise MatrixProvisionError(str(exc)) from exc

        row = await self._users.upsert(
            user_id=user_id,
            mxid=mxid,
            localpart=localpart,
            password_encrypted="",
            provision_status="active",
        )
        log_info(
            logger,
            "Matrix user provision committed",
            matrix_category="provisioning",
            request_id=request_id,
            user_id=user_id,
            mxid=mxid,
        )
        return row


matrix_provisioning_service = MatrixProvisioningService()
