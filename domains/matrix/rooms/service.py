"""Matrix DM room lifecycle."""

from __future__ import annotations

from typing import Any

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
from core.observability.prometheus_metrics import MATRIX_ROOM_PROVISION_TOTAL
from domains.matrix.provisioning.service import MatrixProvisioningService
from infrastructure.database.connection import call_json_function
from infrastructure.database.repositories.conversations import PostgresConversationRepository
from infrastructure.database.repositories.matrix_users import PostgresMatrixUserRepository
from infrastructure.matrix.admin import synapse_admin_client
from infrastructure.matrix.client import create_direct_encrypted_room

logger = get_logger(__name__)


class MatrixRoomProvisionError(RuntimeError):
    """Matrix room cannot be provisioned."""


class MatrixRoomService:
    """Create, archive, and reopen encrypted DM rooms."""

    def __init__(
        self,
        *,
        conversations: PostgresConversationRepository | None = None,
        users: PostgresMatrixUserRepository | None = None,
        provisioning: MatrixProvisioningService | None = None,
    ) -> None:
        self._conversations = conversations or PostgresConversationRepository()
        self._users = users or PostgresMatrixUserRepository()
        self._provisioning = provisioning or MatrixProvisioningService()

    async def provision_dm_for_connection(
        self,
        *,
        connection: dict[str, Any],
        created_by_user_id: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or activate an E2EE DM room for an active connection."""
        if not settings.matrix.enabled:
            raise MatrixRoomProvisionError("Matrix is disabled")

        connection_id = str(connection["id"])
        log_info(
            logger,
            "Matrix room provision request received",
            matrix_category="room_events",
            request_id=request_id,
            connection_id=connection_id,
        )
        mapping = await self._conversations.provision_for_connection(
            connection_id=connection_id,
            created_by_user_id=created_by_user_id,
        )
        if mapping.get("status") == "active" and str(mapping.get("room_id", "")).startswith("!"):
            MATRIX_ROOM_PROVISION_TOTAL.labels(outcome="existing").inc()
            return mapping

        user_a = str(connection["user_a_id"])
        user_b = str(connection["user_b_id"])
        for uid in (user_a, user_b):
            user_row = await call_json_function("fn_users", 2, {"user_id": uid})
            display_name = (user_row or {}).get("display_name") or (user_row or {}).get("email")
            await self._provisioning.ensure_user_provisioned(
                user_id=uid,
                display_name=display_name,
                request_id=request_id,
            )

        creator_mapping = await self._users.get_by_user_id(created_by_user_id)
        peer_id = user_b if created_by_user_id == user_a else user_a
        peer_mapping = await self._users.get_by_user_id(peer_id)
        if not creator_mapping or not peer_mapping:
            await self._conversations.update_mapping(
                connection_id=connection_id,
                status="failed",
            )
            raise MatrixRoomProvisionError("Both users must have Matrix accounts")

        creator_mxid = creator_mapping["mxid"]
        peer_mxid = peer_mapping["mxid"]
        login = await synapse_admin_client.create_login_token(mxid=creator_mxid)
        access_token = login.get("access_token")
        if not access_token:
            await self._conversations.update_mapping(connection_id=connection_id, status="failed")
            raise MatrixRoomProvisionError("Failed to obtain Matrix login token")

        try:
            room_id = await create_direct_encrypted_room(
                access_token=access_token,
                creator_mxid=creator_mxid,
                invite_mxid=peer_mxid,
                room_alias=mapping.get("room_alias"),
            )
        except Exception as exc:
            await self._conversations.update_mapping(connection_id=connection_id, status="failed")
            MATRIX_ROOM_PROVISION_TOTAL.labels(outcome="failed").inc()
            log_warning(
                logger,
                "Matrix room provision failed",
                matrix_category="room_events",
                request_id=request_id,
                connection_id=connection_id,
                reason=str(exc),
            )
            raise MatrixRoomProvisionError(str(exc)) from exc

        updated = await self._conversations.update_mapping(
            connection_id=connection_id,
            room_id=room_id,
            status="active",
        )
        MATRIX_ROOM_PROVISION_TOTAL.labels(outcome="success").inc()
        log_info(
            logger,
            "Matrix room provision committed",
            matrix_category="room_events",
            request_id=request_id,
            connection_id=connection_id,
            room_id=room_id,
        )
        return updated

    async def archive_for_connection(
        self,
        *,
        connection_id: str,
        archived_by_user_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Archive a DM room mapping."""
        return await self._conversations.archive_for_connection(
            connection_id,
            archived_by_user_id=archived_by_user_id,
            reason=reason,
        )

    async def reopen_for_connection(self, *, connection_id: str) -> dict[str, Any]:
        """Reopen an archived DM room mapping."""
        return await self._conversations.reopen_for_connection(connection_id)

    async def archive_connection_room(
        self,
        connection_id: str,
        *,
        archived_by_user_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Archive a DM room mapping (router alias)."""
        return await self.archive_for_connection(
            connection_id=connection_id,
            archived_by_user_id=archived_by_user_id,
            reason=reason,
        )

    async def reopen_connection_room(self, connection_id: str) -> dict[str, Any]:
        """Reopen an archived DM room mapping (router alias)."""
        return await self.reopen_for_connection(connection_id=connection_id)


matrix_room_service = MatrixRoomService()


async def maybe_auto_provision_on_accept(
    connection: dict[str, Any],
    *,
    accepted_by_user_id: str,
    request_id: str | None = None,
) -> None:
    """Provision Matrix DM when a connection is accepted."""
    if not settings.matrix.enabled:
        return
    try:
        await matrix_room_service.provision_dm_for_connection(
            connection=connection,
            created_by_user_id=accepted_by_user_id,
            request_id=request_id,
        )
    except MatrixRoomProvisionError:
        return
