"""Matrix DM room lifecycle."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
from domains.auth.security import now_utc
from domains.chat.permissions import is_provisioned_room_id
from domains.matrix.provisioning.service import MatrixProvisionError, MatrixProvisioningService
from infrastructure.database.connection import call_json_function, get_pool
from infrastructure.database.repositories.conversations import PostgresConversationRepository
from infrastructure.database.repositories.matrix_users import PostgresMatrixUserRepository
from infrastructure.matrix.admin import synapse_admin_client
from infrastructure.matrix.client import create_direct_encrypted_room, reconcile_encrypted_room

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
        self, *, connection: dict[str, Any], created_by_user_id: str, request_id: str | None = None
    ) -> dict[str, Any]:
        """Persist intent first; serialize creation and reconcile any ambiguous remote outcome."""
        if connection.get("status") != "active" or str(created_by_user_id) not in {
            str(connection["user_a_id"]),
            str(connection["user_b_id"]),
        }:
            raise MatrixRoomProvisionError("Active connection membership required")
        from infrastructure.database.repositories.matching import PostgresMatchingRepository

        if await PostgresMatchingRepository().is_blocked(
            str(connection["user_a_id"]), str(connection["user_b_id"])
        ):
            raise MatrixRoomProvisionError("Blocked connection cannot provision a room")
        pool = await get_pool()
        cid = str(connection["id"])
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO matrix_room_operations(connection_id,creator_user_id)
                VALUES($1::uuid,$2::uuid) ON CONFLICT(connection_id) DO NOTHING""",
                cid,
                created_by_user_id,
            )
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "matrix-room:" + cid
            )
            try:
                result = await self._provision(
                    connection=connection,
                    created_by_user_id=created_by_user_id,
                    request_id=request_id,
                )
            except Exception as exc:
                await conn.execute(
                    """UPDATE matrix_room_operations SET
                    status='pending',attempts=attempts+1,last_error=$2,next_attempt_at=now()+interval
                    '30 seconds' WHERE connection_id=$1::uuid""",
                    cid,
                    type(exc).__name__,
                )
                failure = exc
            else:
                await conn.execute(
                    """UPDATE matrix_room_operations SET status='complete',last_error=NULL
                    WHERE connection_id=$1::uuid""",
                    cid,
                )
                failure = None
        if failure:
            raise MatrixRoomProvisionError("Room provisioning pending reconciliation") from failure
        return result

    async def _provision(
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
        if mapping.get("status") in {"invited", "joined", "active"} and is_provisioned_room_id(
            mapping.get("room_id")
        ):
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

        created_by_user_id = str(mapping["created_by_user_id"])
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
        login = await synapse_admin_client.create_login_token(
            mxid=creator_mxid,
            valid_until_ms=int((now_utc() + timedelta(minutes=5)).timestamp() * 1000),
        )
        access_token = login.get("access_token")
        if not access_token:
            await self._conversations.update_mapping(connection_id=connection_id, status="failed")
            raise MatrixRoomProvisionError("Failed to obtain Matrix login token")

        try:
            alias = f"#conn_{connection_id}:{settings.matrix.server_name}"
            room_id = await reconcile_encrypted_room(
                access_token=access_token,
                room_alias=alias,
                expected_members={creator_mxid, peer_mxid},
            )
            if room_id is None:
                room_id = await create_direct_encrypted_room(
                    access_token=access_token,
                    creator_mxid=creator_mxid,
                    invite_mxid=peer_mxid,
                    room_alias=alias,
                )
        except Exception as exc:
            await self._conversations.update_mapping(connection_id=connection_id, status="failed")
            log_warning(
                logger,
                "Matrix room provision failed",
                matrix_category="room_events",
                request_id=request_id,
                connection_id=connection_id,
                reason=type(exc).__name__,
            )
            raise MatrixRoomProvisionError(str(exc)) from exc

        updated = await self._conversations.update_mapping(
            connection_id=connection_id,
            room_id=room_id,
            status="invited",
            room_alias=alias,
        )
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
        user_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Archive a connection in the user's inbox."""
        return await self._conversations.archive_for_connection(
            connection_id,
            user_id=user_id,
            reason=reason,
        )

    async def reopen_for_connection(
        self,
        *,
        connection_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Remove a connection from the user's archived inbox."""
        return await self._conversations.reopen_for_connection(connection_id, user_id=user_id)

    async def archive_connection_room(
        self,
        connection_id: str,
        *,
        user_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Archive a connection in the user's inbox (router alias)."""
        return await self.archive_for_connection(
            connection_id=connection_id,
            user_id=user_id,
            reason=reason,
        )

    async def reopen_connection_room(self, connection_id: str, *, user_id: str) -> dict[str, Any]:
        """Remove a connection from the user's archived inbox (router alias)."""
        return await self.reopen_for_connection(connection_id=connection_id, user_id=user_id)


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
    except (MatrixRoomProvisionError, MatrixProvisionError) as exc:
        log_warning(
            logger,
            "Matrix auto-provision skipped after connection accept",
            matrix_category="room_events",
            request_id=request_id,
            connection_id=str(connection.get("id", "")),
            reason=str(exc),
        )
    except Exception as exc:
        log_warning(
            logger,
            "Matrix auto-provision failed after connection accept",
            matrix_category="room_events",
            request_id=request_id,
            connection_id=str(connection.get("id", "")),
            reason=str(exc),
        )


async def retry_room_operations() -> None:
    """Retry durable provisioning without changing the original creator or connection policy."""
    from infrastructure.database.repositories.matching import PostgresMatchingRepository

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT * FROM matrix_room_operations WHERE status='pending' AND
            next_attempt_at<=now() LIMIT 20""")
    for row in rows:
        connection = await PostgresMatchingRepository().get_connection(str(row["connection_id"]))
        if not connection or connection.get("status") != "active":
            continue
        try:
            await matrix_room_service.provision_dm_for_connection(
                connection=connection, created_by_user_id=str(row["creator_user_id"])
            )
        except MatrixRoomProvisionError:
            pass
