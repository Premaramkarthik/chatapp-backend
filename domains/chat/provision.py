"""Provision Tinode P2P conversation mappings for active connections."""

from __future__ import annotations

from typing import Any

from core.logging.logger import get_logger, log_info, log_warning
from infrastructure.database.connection import call_json_function
from infrastructure.database.repositories.conversations import PostgresConversationRepository
from infrastructure.tinode.grpc_client import TinodeGrpcError, prepare_p2p_conversation

logger = get_logger(__name__)


class ProvisionError(RuntimeError):
    """Conversation cannot be provisioned."""


async def provision_conversation_for_connection(
    *,
    connection: dict[str, Any],
    created_by_user_id: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create or activate a Tinode mapping with real P2P topic identifiers."""
    connection_id = str(connection["id"])
    log_info(
        logger,
        "Conversation provision request received",
        request_id=request_id,
        connection_id=connection_id,
        created_by_user_id=created_by_user_id,
    )
    repo = PostgresConversationRepository()
    mapping = await repo.provision_for_connection(
        connection_id=connection_id,
        created_by_user_id=created_by_user_id,
    )
    if mapping.get("status") == "active" and mapping.get("tinode_topic_id", "").startswith("p2p"):
        log_info(
            logger,
            "Conversation provision committed with active Tinode mapping",
            request_id=request_id,
            connection_id=connection_id,
            tinode_topic_id=mapping.get("tinode_topic_id"),
            status="active",
        )
        return mapping

    user_a = str(connection["user_a_id"])
    user_b = str(connection["user_b_id"])
    tum_a = await call_json_function("fn_tinode_user_mappings", 2, {"user_id": user_a})
    tum_b = await call_json_function("fn_tinode_user_mappings", 2, {"user_id": user_b})
    if not tum_a or not tum_a.get("tinode_user_id") or not tum_b or not tum_b.get("tinode_user_id"):
        await repo.update_mapping(
            connection_id=connection_id,
            status="failed",
        )
        log_warning(
            logger,
            "Conversation provision failed because Tinode is not linked for both users",
            request_id=request_id,
            connection_id=connection_id,
        )
        raise ProvisionError("Both users must complete Tinode link before provisioning")

    peer_id = user_b if created_by_user_id == user_a else user_a
    peer_user = await call_json_function("fn_users", 2, {"user_id": peer_id})
    peer_name = (peer_user or {}).get("display_name") or (peer_user or {}).get("email")

    try:
        result = await prepare_p2p_conversation(
            tinode_uid_a=tum_a["tinode_user_id"],
            tinode_uid_b=tum_b["tinode_user_id"],
            connection_id=connection_id,
            peer_display_name=peer_name,
        )
    except TinodeGrpcError as exc:
        await repo.update_mapping(
            connection_id=connection_id,
            status="failed",
        )
        log_warning(
            logger,
            "Conversation provision failed",
            request_id=request_id,
            connection_id=connection_id,
            reason=str(exc),
        )
        raise ProvisionError(str(exc)) from exc

    topic_name = (
        result.names.topic_for_user_a
        if created_by_user_id == user_a
        else result.names.topic_for_user_b
    )
    updated = await repo.update_mapping(
        connection_id=connection_id,
        tinode_topic_id=result.names.internal_topic_id,
        tinode_topic_name=topic_name,
        status="active",
    )
    log_info(
        logger,
        "Conversation provision committed with active Tinode mapping",
        request_id=request_id,
        connection_id=connection_id,
        tinode_topic_id=updated.get("tinode_topic_id"),
        status="active",
    )
    return updated


async def maybe_auto_provision_on_accept(
    connection: dict[str, Any],
    *,
    accepted_by_user_id: str,
) -> None:
    """Optionally provision chat when a connection is accepted."""
    from core.config.settings import settings

    if not settings.tinode.auto_provision_on_accept:
        return
    try:
        await provision_conversation_for_connection(
            connection=connection,
            created_by_user_id=accepted_by_user_id,
        )
    except ProvisionError:
        return
