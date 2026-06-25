"""Connection request routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.logging.logger import get_logger, log_info, log_warning
from domains.matrix.rooms.service import maybe_auto_provision_on_accept
from infrastructure.database.repositories.connection_screens import ConnectionScreenRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.database.repositories.notifications import PostgresNotificationRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.account_mode import ConnectorUser
from v1.dependencies.auth import get_current_principal, require_capability
from v1.schemas.connection_screens import (
    ActiveConnectionItem,
    ActiveConnectionsResponse,
    ConnectionsSummaryResponse,
    HistoryItem,
    HistoryResponse,
    IncomingRequestItem,
    IncomingRequestsResponse,
    SentRequestItem,
    SentRequestsResponse,
)
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
TripJoiner = Annotated[KeycloakPrincipal, Depends(require_capability("trip:join"))]


async def _local_user_id(principal: KeycloakPrincipal) -> str:
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.id


async def _notify(user_id: str, notification_type: str, payload: dict) -> None:
    await PostgresNotificationRepository().create_notification(
        user_id,
        notification_type,
        payload,
    )


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
    await _notify(
        str(payload.recipient_id),
        "connection_request",
        {"request_id": str(row.get("id")), "requester_id": requester_id},
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
    request_row = await repo.get_request(str(request_id))
    if request_row is not None:
        await _notify(
            str(request_row["requester_id"]),
            "connection_accepted",
            {"connection_id": str(row.get("id")), "recipient_id": recipient_id},
        )
    log_info(
        logger,
        "Connection request accepted",
        request_id=correlation_id,
        connection_id=row.get("id"),
        recipient_id=recipient_id,
    )
    await maybe_auto_provision_on_accept(
        row,
        accepted_by_user_id=recipient_id,
        request_id=correlation_id,
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


@router.get("", response_model=list[UserConnectionResponse])
async def list_connections(
    _: MessageSender,
    principal: CurrentPrincipal,
) -> list[UserConnectionResponse]:
    """List active connections for the current user."""
    user_id = await _local_user_id(principal)
    rows = await PostgresMatchingRepository().list_connections(user_id)
    return [UserConnectionResponse(**row) for row in rows]


@router.get("/requests/outgoing", response_model=list[ConnectionRequestResponse])
async def list_outgoing_requests(
    _: MessageSender,
    principal: CurrentPrincipal,
) -> list[ConnectionRequestResponse]:
    """List pending outgoing connection requests."""
    requester_id = await _local_user_id(principal)
    rows = await PostgresMatchingRepository().list_outgoing_requests(requester_id)
    return [ConnectionRequestResponse(**row) for row in rows]


@router.post("/requests/{request_id}/cancel", response_model=ConnectionRequestResponse)
async def cancel_connection_request(
    request: Request,
    request_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> ConnectionRequestResponse:
    """Cancel a pending outgoing connection request."""
    correlation_id = request_id_from(request)
    requester_id = await _local_user_id(principal)
    repo = PostgresMatchingRepository()
    try:
        row = await repo.cancel_request(str(request_id), requester_id)
    except ValueError as exc:
        log_warning(
            logger,
            "Connection cancel failed",
            request_id=correlation_id,
            connection_request_id=str(request_id),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        ) from exc
    log_info(
        logger,
        "Connection request cancelled",
        request_id=correlation_id,
        connection_request_id=str(request_id),
        requester_id=requester_id,
    )
    return ConnectionRequestResponse(**row)


@router.delete("/{connection_id}", response_model=UserConnectionResponse)
async def remove_connection(
    request: Request,
    connection_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> UserConnectionResponse:
    """Soft-remove an active connection."""
    correlation_id = request_id_from(request)
    user_id = await _local_user_id(principal)
    repo = PostgresMatchingRepository()
    try:
        row = await repo.remove_connection(str(connection_id), user_id)
    except ValueError as exc:
        log_warning(
            logger,
            "Connection remove failed",
            request_id=correlation_id,
            connection_id=str(connection_id),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found",
        ) from exc
    log_info(
        logger,
        "Connection removed",
        request_id=correlation_id,
        connection_id=str(connection_id),
        user_id=user_id,
    )
    return UserConnectionResponse(**row)


@router.get("/screens/summary", response_model=ConnectionsSummaryResponse)
async def connections_screen_summary(
    _: TripJoiner,
    user: ConnectorUser,
) -> ConnectionsSummaryResponse:
    """Return tab counts for the connector connections hub."""
    counts = await ConnectionScreenRepository().summary(user.id)
    return ConnectionsSummaryResponse(**counts)


@router.get("/screens/incoming", response_model=IncomingRequestsResponse)
async def connections_screen_incoming(
    _: TripJoiner,
    user: ConnectorUser,
) -> IncomingRequestsResponse:
    """Return pending incoming requests with enriched peer cards."""
    rows = await ConnectionScreenRepository().list_incoming(user.id)
    return IncomingRequestsResponse(
        items=[IncomingRequestItem(**row) for row in rows],
    )


@router.get("/screens/sent", response_model=SentRequestsResponse)
async def connections_screen_sent(
    _: TripJoiner,
    user: ConnectorUser,
) -> SentRequestsResponse:
    """Return pending outgoing requests with enriched peer cards."""
    rows = await ConnectionScreenRepository().list_sent(user.id)
    return SentRequestsResponse(items=[SentRequestItem(**row) for row in rows])


@router.get("/screens/active", response_model=ActiveConnectionsResponse)
async def connections_screen_active(
    _: TripJoiner,
    user: ConnectorUser,
) -> ActiveConnectionsResponse:
    """Return active connections with enriched peer cards."""
    rows = await ConnectionScreenRepository().list_active(user.id)
    return ActiveConnectionsResponse(
        items=[ActiveConnectionItem(**row) for row in rows],
    )


@router.get("/screens/history", response_model=HistoryResponse)
async def connections_screen_history(
    _: TripJoiner,
    user: ConnectorUser,
    limit: int = 50,
) -> HistoryResponse:
    """Return terminal requests and removed connections."""
    rows = await ConnectionScreenRepository().list_history(user.id, limit=limit)
    return HistoryResponse(items=[HistoryItem(**row) for row in rows])
