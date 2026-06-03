"""Chat conversation provisioning routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from core.observability.prometheus_metrics import TINODE_PROVISION_TOTAL
from domains.chat.provision import ProvisionError, provision_conversation_for_connection
from domains.chat.session import TinodeSessionNotReadyError, build_tinode_session
from infrastructure.database.repositories.conversations import PostgresConversationRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.schemas.chat import (
    ConversationMappingSummary,
    ConversationProvisionRequest,
    ConversationResponse,
    InboxItem,
    InboxPeer,
    InboxResponse,
    TinodeSessionResponse,
)
from v1.schemas.principal import KeycloakPrincipal

router = APIRouter(prefix="/v1/chat", tags=["chat"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
RoomCreator = Annotated[KeycloakPrincipal, Depends(require_capability("message:create-room"))]
MessageSender = Annotated[KeycloakPrincipal, Depends(require_capability("message:send"))]


async def _local_user(principal: KeycloakPrincipal) -> dict:
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.to_dict()


async def _require_active_connection(connection_id: str, user_id: str) -> dict:
    connection = await PostgresMatchingRepository().get_connection(connection_id)
    if connection is None or connection.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    if user_id not in (str(connection["user_a_id"]), str(connection["user_b_id"])):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a connection member")
    if await PostgresMatchingRepository().is_blocked(
        user_id,
        (
            str(connection["user_b_id"])
            if user_id == str(connection["user_a_id"])
            else str(connection["user_a_id"])
        ),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User blocked")
    return connection


@router.get(
    "/tinode-session",
    response_model=TinodeSessionResponse,
    summary="Obtain Tinode WebSocket login secret",
)
async def tinode_session(
    principal: CurrentPrincipal,
) -> TinodeSessionResponse:
    """Return base64 login secret and Tinode web URL for the authenticated user."""
    user = await _local_user(principal)
    try:
        payload = await build_tinode_session(user=user)
    except TinodeSessionNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return TinodeSessionResponse(**payload)


@router.get(
    "/inbox",
    response_model=InboxResponse,
    summary="List 1:1 chat-eligible connections",
)
async def chat_inbox(
    _: MessageSender,
    principal: CurrentPrincipal,
) -> InboxResponse:
    """List active connections with peer profile and Tinode mapping metadata."""
    user = await _local_user(principal)
    rows = await PostgresConversationRepository().list_inbox(user["id"])
    items = [
        InboxItem(
            connection_id=row["connection_id"],
            connection_status=row["connection_status"],
            connected_at=row.get("connected_at"),
            peer=InboxPeer(**row["peer"]),
            mapping=(ConversationMappingSummary(**row["mapping"]) if row.get("mapping") else None),
            can_chat=bool(row.get("can_chat")),
        )
        for row in rows
    ]
    return InboxResponse(items=items)


@router.get(
    "/conversations/{connection_id}",
    response_model=ConversationResponse,
    summary="Get Tinode mapping for a connection",
)
async def get_conversation(
    connection_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> ConversationResponse:
    """Return conversation mapping for one connection."""
    user = await _local_user(principal)
    await _require_active_connection(str(connection_id), user["id"])
    mapping = await PostgresConversationRepository().get_by_connection(str(connection_id))
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    return ConversationResponse(**mapping)


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision Tinode P2P topic for a connection",
)
async def provision_conversation(
    payload: ConversationProvisionRequest,
    _: RoomCreator,
    principal: CurrentPrincipal,
) -> ConversationResponse:
    """Provision a Tinode topic mapping for an active connection."""
    user = await _local_user(principal)
    connection = await _require_active_connection(str(payload.connection_id), user["id"])
    try:
        mapping = await provision_conversation_for_connection(
            connection=connection,
            created_by_user_id=user["id"],
        )
        TINODE_PROVISION_TOTAL.labels(outcome="success").inc()
    except ProvisionError as exc:
        TINODE_PROVISION_TOTAL.labels(outcome="failed").inc()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return ConversationResponse(**mapping)


@router.post(
    "/conversations/{connection_id}/archive",
    response_model=ConversationResponse,
    summary="Archive conversation mapping",
)
async def archive_conversation(
    connection_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> ConversationResponse:
    """Archive mapping (e.g. after block); messaging should stop on client side."""
    user = await _local_user(principal)
    await _require_active_connection(str(connection_id), user["id"])
    try:
        mapping = await PostgresConversationRepository().archive_for_connection(str(connection_id))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mapping not found",
        ) from exc
    return ConversationResponse(**mapping)
