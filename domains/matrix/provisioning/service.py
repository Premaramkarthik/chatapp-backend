"""Matrix user provisioning."""

from __future__ import annotations

import secrets
from typing import Any

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
from core.observability.prometheus_metrics import MATRIX_PROVISION_TOTAL
from domains.auth.security import TokenCipher
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
        cipher: TokenCipher | None = None,
    ) -> None:
        self._users = users or PostgresMatrixUserRepository()
        self._cipher = cipher or TokenCipher()

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
        if existing and existing.get("provision_status") == "active":
            return existing

        localpart = matrix_localpart_for_user(user_id)
        mxid = matrix_mxid_for_localpart(localpart)
        password = secrets.token_urlsafe(32)

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
                password=password,
                displayname=display_name,
            )
        except MatrixIntegrationError as exc:
            MATRIX_PROVISION_TOTAL.labels(outcome="failed").inc()
            log_warning(
                logger,
                "Matrix user provision failed",
                matrix_category="provisioning",
                request_id=request_id,
                user_id=user_id,
                reason=str(exc),
            )
            raise MatrixProvisionError(str(exc)) from exc

        row = await self._users.upsert(
            user_id=user_id,
            mxid=mxid,
            localpart=localpart,
            password_encrypted=self._cipher.encrypt(password) or "",
            provision_status="active",
        )
        MATRIX_PROVISION_TOTAL.labels(outcome="success").inc()
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
