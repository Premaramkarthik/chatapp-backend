"""Connector profile routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from core.logging.logger import get_logger, log_info
from domains.geo.display import enrich_home_location
from infrastructure.database.repositories.connectors import PostgresConnectorRepository
from v1.dependencies.account_mode import ConnectorUser
from v1.schemas.connectors import ConnectorProfileResponse, ConnectorProfileUpdateRequest
from v1.utils.request_context import request_id_from

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


@router.get("/profile", response_model=ConnectorProfileResponse)
async def get_connector_profile(user: ConnectorUser) -> ConnectorProfileResponse:
    """Return the authenticated user's connector profile."""
    row = await PostgresConnectorRepository().get_connector_profile(user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    fields = {k: v for k, v in row.items() if k != "user_id"}
    fields.update(await enrich_home_location(row))
    preferred = fields.get("preferred_destination_countries") or []
    if preferred and isinstance(preferred, list):
        fields["preferred_destination_countries"] = [str(c).upper() for c in preferred]
    return ConnectorProfileResponse(user_id=UUID(row["user_id"]), **fields)


@router.put("/profile", response_model=ConnectorProfileResponse)
async def upsert_connector_profile(
    request: Request,
    payload: ConnectorProfileUpdateRequest,
    user: ConnectorUser,
) -> ConnectorProfileResponse:
    """Create or update connector profile."""
    request_id = request_id_from(request)
    log_info(
        logger,
        "Connector profile upsert request received",
        request_id=request_id,
        user_id=user.id,
    )
    row = await PostgresConnectorRepository().upsert_connector_profile(
        user.id,
        **payload.model_dump(exclude_unset=True),
    )
    log_info(
        logger,
        "Connector profile upsert committed",
        request_id=request_id,
        user_id=user.id,
    )
    fields = {k: v for k, v in row.items() if k != "user_id"}
    fields.update(await enrich_home_location(row))
    preferred = fields.get("preferred_destination_countries") or []
    if preferred and isinstance(preferred, list):
        fields["preferred_destination_countries"] = [str(c).upper() for c in preferred]
    return ConnectorProfileResponse(user_id=UUID(row["user_id"]), **fields)
