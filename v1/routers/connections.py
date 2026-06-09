"""Connection request routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.logging.logger import get_logger, log_info, log_warning
from domains.chat.provision import maybe_auto_provision_on_accept
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.schemas.connections import (
    ConnectionRequestCreate,
    ConnectionRequestResponse,
    UserConnectionResponse,
)
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.request_context import request_id_from

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/connections", tags=["connections"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
MessageSender = Annotated[KeycloakPrincipal, Depends(require_capability("message:send"))]


async def _local_user_id(principal: KeycloakPrincipal) -> str:
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.id


@router.post(
    "/requests",
    response_model=ConnectionRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection_request(
    request: Request,
    payload: ConnectionRequestCreate,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> ConnectionRequestResponse:
    """Send a connection request to another user."""
    request_id = request_id_from(request)
    requester_id = await _local_user_id(principal)
    log_info(
        logger,
        "Connection request received",
        request_id=request_id,
        requester_id=requester_id,
        recipient_id=str(payload.recipient_id),
    )
    if str(payload.recipient_id) == requester_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot request self")

    repo = PostgresMatchingRepository()
    try:
        row = await repo.create_connection_request(
            requester_id,
            str(payload.recipient_id),
            payload.message,
        )
    except ValueError as exc:
        if str(exc) == "blocked":
            log_warning(
                logger,
                "Connection request failed because users are blocked",
                request_id=request_id,
                requester_id=requester_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User blocked",
            ) from exc
        raise
    log_info(
        logger,
        "Connection request created",
        request_id=request_id,
        request_id_row=row.get("id"),
        requester_id=requester_id,
        recipient_id=str(payload.recipient_id),
    )
    return ConnectionRequestResponse(**row)


@router.get("/requests/incoming", response_model=list[ConnectionRequestResponse])
async def list_incoming_requests(
    _: MessageSender,
    principal: CurrentPrincipal,
) -> list[ConnectionRequestResponse]:
    """List pending incoming connection requests."""
    recipient_id = await _local_user_id(principal)
    rows = await PostgresMatchingRepository().list_incoming_requests(recipient_id)
    return [ConnectionRequestResponse(**row) for row in rows]


@router.post("/requests/{request_id}/accept", response_model=UserConnectionResponse)
async def accept_connection_request(
    request: Request,
    request_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> UserConnectionResponse:
    """Accept a connection request (mutual accept creates user_connections)."""
    correlation_id = request_id_from(request)
    recipient_id = await _local_user_id(principal)
    log_info(
        logger,
        "Connection accept request received",
        request_id=correlation_id,
        connection_request_id=str(request_id),
        recipient_id=recipient_id,
    )
    repo = PostgresMatchingRepository()
    try:
        row = await repo.accept_request(str(request_id), recipient_id)
    except ValueError as exc:
        code = str(exc)
        log_warning(
            logger,
            "Connection accept failed",
            request_id=correlation_id,
            connection_request_id=str(request_id),
            reason=code,
        )
        if code == "not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Request not found",
            ) from exc
        if code == "forbidden":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invalid request state",
        ) from exc
    await maybe_auto_provision_on_accept(row, accepted_by_user_id=recipient_id)
    log_info(
        logger,
        "Connection request accepted",
        request_id=correlation_id,
        connection_id=row.get("id"),
        recipient_id=recipient_id,
    )
    return UserConnectionResponse(**row)


@router.post("/requests/{request_id}/reject", response_model=ConnectionRequestResponse)
async def reject_connection_request(
    request: Request,
    request_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> ConnectionRequestResponse:
    """Reject a pending connection request."""
    correlation_id = request_id_from(request)
    recipient_id = await _local_user_id(principal)
    log_info(
        logger,
        "Connection reject request received",
        request_id=correlation_id,
        connection_request_id=str(request_id),
        recipient_id=recipient_id,
    )
    repo = PostgresMatchingRepository()
    try:
        row = await repo.reject_request(str(request_id), recipient_id)
    except ValueError as exc:
        log_warning(
            logger,
            "Connection reject failed because request was not found",
            request_id=correlation_id,
            connection_request_id=str(request_id),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        ) from exc
    log_info(
        logger,
        "Connection request rejected",
        request_id=correlation_id,
        connection_request_id=str(request_id),
        recipient_id=recipient_id,
    )
    return ConnectionRequestResponse(**row)
