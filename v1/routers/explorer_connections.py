"""Explorer connection hub screen routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from infrastructure.database.repositories.connection_screens import ConnectionScreenRepository
from v1.dependencies.account_mode import ExplorerUser
from v1.dependencies.auth import require_capability
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
from v1.schemas.principal import KeycloakPrincipal

router = APIRouter(prefix="/v1/explorers/connections", tags=["explorers"])
TripCreator = Annotated[KeycloakPrincipal, Depends(require_capability("trip:create"))]


@router.get("/screens/summary", response_model=ConnectionsSummaryResponse)
async def explorer_connections_screen_summary(
    _: TripCreator,
    user: ExplorerUser,
) -> ConnectionsSummaryResponse:
    """Return tab counts for the explorer connections hub."""
    counts = await ConnectionScreenRepository().summary(user.id)
    return ConnectionsSummaryResponse(**counts)


@router.get("/screens/incoming", response_model=IncomingRequestsResponse)
async def explorer_connections_screen_incoming(
    _: TripCreator,
    user: ExplorerUser,
) -> IncomingRequestsResponse:
    """Return pending incoming requests with enriched peer cards."""
    rows = await ConnectionScreenRepository().list_incoming(user.id)
    return IncomingRequestsResponse(
        items=[IncomingRequestItem(**row) for row in rows],
    )


@router.get("/screens/sent", response_model=SentRequestsResponse)
async def explorer_connections_screen_sent(
    _: TripCreator,
    user: ExplorerUser,
) -> SentRequestsResponse:
    """Return pending outgoing requests with enriched peer cards."""
    rows = await ConnectionScreenRepository().list_sent(user.id)
    return SentRequestsResponse(items=[SentRequestItem(**row) for row in rows])


@router.get("/screens/active", response_model=ActiveConnectionsResponse)
async def explorer_connections_screen_active(
    _: TripCreator,
    user: ExplorerUser,
) -> ActiveConnectionsResponse:
    """Return active connections with enriched peer cards."""
    rows = await ConnectionScreenRepository().list_active(user.id)
    return ActiveConnectionsResponse(
        items=[ActiveConnectionItem(**row) for row in rows],
    )


@router.get("/screens/history", response_model=HistoryResponse)
async def explorer_connections_screen_history(
    _: TripCreator,
    user: ExplorerUser,
    limit: int = 50,
) -> HistoryResponse:
    """Return terminal requests and removed connections."""
    rows = await ConnectionScreenRepository().list_history(user.id, limit=limit)
    return HistoryResponse(items=[HistoryItem(**row) for row in rows])
