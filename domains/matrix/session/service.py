"""Matrix client session issuance."""

from __future__ import annotations

import time
from typing import Any

from core.config.settings import settings
from core.logging.logger import get_logger, log_info
from core.observability.prometheus_metrics import MATRIX_SESSION_TOTAL
from domains.matrix.provisioning.service import MatrixProvisioningService
from infrastructure.database.repositories.matrix_users import PostgresMatrixUserRepository
from infrastructure.matrix.admin import synapse_admin_client
from infrastructure.matrix.session_cache import (
    cache_matrix_session,
    get_cached_matrix_session,
    invalidate_matrix_session,
)

logger = get_logger(__name__)


class MatrixSessionNotReadyError(RuntimeError):
    """User has not completed Matrix provisioning yet."""


class MatrixSessionService:
    """Issue short-lived Matrix login tokens for matrix-js-sdk."""

    def __init__(
        self,
        *,
        users: PostgresMatrixUserRepository | None = None,
        provisioning: MatrixProvisioningService | None = None,
    ) -> None:
        self._users = users or PostgresMatrixUserRepository()
        self._provisioning = provisioning or MatrixProvisioningService()

    async def create_session(
        self,
        *,
        user: dict[str, Any],
        request_id: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return Matrix homeserver credentials for the authenticated user."""
        if not settings.matrix.enabled:
            raise MatrixSessionNotReadyError("Matrix is disabled")

        user_id = str(user["id"])
        if not force_refresh:
            cached = await get_cached_matrix_session(user_id)
            if cached:
                MATRIX_SESSION_TOTAL.labels(outcome="cache_hit").inc()
                return self._session_payload(user=user, **cached)

        mapping = await self._users.get_by_user_id(user_id)
        if not mapping or mapping.get("provision_status") != "active":
            await self._provisioning.ensure_user_provisioned(
                user_id=user_id,
                display_name=user.get("display_name") or user.get("email"),
                request_id=request_id,
            )
            mapping = await self._users.get_by_user_id(user_id)
        if not mapping:
            MATRIX_SESSION_TOTAL.labels(outcome="not_ready").inc()
            raise MatrixSessionNotReadyError("Matrix account not linked")

        valid_until_ms = int((time.time() + settings.matrix.access_token_ttl_sec) * 1000)
        login = await synapse_admin_client.create_login_token(
            mxid=mapping["mxid"],
            valid_until_ms=valid_until_ms,
        )
        access_token = login.get("access_token")
        if not access_token:
            MATRIX_SESSION_TOTAL.labels(outcome="failed").inc()
            raise MatrixSessionNotReadyError("Matrix login token unavailable")

        device_id = login.get("device_id")
        expires_in = settings.matrix.access_token_ttl_sec
        await cache_matrix_session(
            user_id,
            access_token=access_token,
            device_id=device_id,
            mxid=mapping["mxid"],
            expires_in=expires_in,
        )
        MATRIX_SESSION_TOTAL.labels(outcome="success").inc()
        log_info(
            logger,
            "Matrix session committed",
            matrix_category="security",
            request_id=request_id,
            user_id=user_id,
            mxid=mapping["mxid"],
        )
        payload = self._session_payload(
            user=user,
            access_token=access_token,
            device_id=device_id,
            mxid=mapping["mxid"],
            expires_in=expires_in,
        )
        return payload

    async def refresh_session(
        self,
        *,
        user: dict[str, Any] | None = None,
        user_id: str | None = None,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Force-refresh Matrix credentials."""
        if user is not None:
            await invalidate_matrix_session(str(user["id"]))
            return await self.create_session(user=user, request_id=request_id, force_refresh=True)
        if user_id is None:
            raise MatrixSessionNotReadyError("user or user_id is required")
        await invalidate_matrix_session(user_id)
        return await self.get_or_create_session(
            user_id=user_id,
            display_name=display_name,
            request_id=request_id,
        )

    async def get_or_create_session(
        self,
        *,
        user_id: str,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Return a Matrix session for a local user id."""
        if not settings.matrix.enabled:
            return {
                "enabled": False,
                "homeserver_url": None,
                "sliding_sync_url": None,
                "access_token": None,
                "user_id": user_id,
                "device_id": None,
                "expires_in_sec": None,
            }
        payload = await self.create_session(
            user={"id": user_id, "display_name": display_name},
            request_id=request_id,
        )
        return {
            "enabled": True,
            "homeserver_url": payload["homeserver_url"],
            "sliding_sync_url": payload["sliding_sync_url"],
            "access_token": payload["access_token"],
            "user_id": str(payload["user_id"]),
            "device_id": payload.get("device_id"),
            "expires_in_sec": payload["expires_in"],
        }

    @staticmethod
    def _session_payload(
        *,
        user: dict[str, Any],
        access_token: str,
        device_id: str | None,
        mxid: str,
        expires_in: int,
    ) -> dict[str, Any]:
        """Build API session payload for matrix-js-sdk."""
        return {
            "homeserver_url": settings.matrix.client_homeserver_url,
            "sliding_sync_url": settings.matrix.client_sliding_sync_url,
            "access_token": access_token,
            "device_id": device_id,
            "user_id": user["id"],
            "matrix_user_id": mxid,
            "expires_in": expires_in,
        }


matrix_session_service = MatrixSessionService()
