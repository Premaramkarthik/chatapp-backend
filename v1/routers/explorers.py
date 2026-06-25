"""Explorer profile, trips, and location routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.logging.logger import get_logger, log_info
from domains.geo.display import enrich_home_location
from infrastructure.database.repositories.explorers import PostgresExplorerRepository
from infrastructure.database.repositories.privacy import PostgresPrivacyRepository
from infrastructure.database.repositories.trips import PostgresTripRepository
from v1.dependencies.account_mode import ConnectorUser, ExplorerUser
from v1.dependencies.auth import require_capability
from v1.routers.connector_search import search_explorers_by_route
from v1.schemas.connector_search import ExplorerSearchResponse
from v1.schemas.explorers import (
    CurrentLocationUpdateRequest,
    ExplorerProfileResponse,
    ExplorerProfileUpdateRequest,
    TravelPlanCreateRequest,
)
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.privacy import PrivacySettingsResponse, PrivacySettingsUpdateRequest
from v1.utils.request_context import request_id_from

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/explorers", tags=["explorers"])
TripCreator = Annotated[KeycloakPrincipal, Depends(require_capability("trip:create"))]
TripSearcher = Annotated[KeycloakPrincipal, Depends(require_capability("trip:join"))]


@router.get("/profile", response_model=ExplorerProfileResponse)
async def get_explorer_profile(user: ExplorerUser) -> ExplorerProfileResponse:
    """Return the authenticated user's explorer profile."""
    row = await PostgresExplorerRepository().get_explorer_profile(user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    fields = {k: v for k, v in row.items() if k != "user_id"}
    fields.update(await enrich_home_location(row))
    return ExplorerProfileResponse(user_id=UUID(row["user_id"]), **fields)


@router.put("/profile", response_model=ExplorerProfileResponse)
async def upsert_explorer_profile(
    request: Request,
    payload: ExplorerProfileUpdateRequest,
    _: TripCreator,
    user: ExplorerUser,
) -> ExplorerProfileResponse:
    """Create or update explorer profile and rebuild discovery snapshot."""
    request_id = request_id_from(request)
    log_info(
        logger,
        "Explorer profile upsert request received",
        request_id=request_id,
        user_id=user.id,
    )
    row = await PostgresExplorerRepository().upsert_explorer_profile(
        user.id,
        **payload.model_dump(exclude_unset=True),
    )
    log_info(
        logger,
        "Explorer profile upsert committed",
        request_id=request_id,
        user_id=user.id,
    )
    fields = {k: v for k, v in row.items() if k != "user_id"}
    fields.update(await enrich_home_location(row))
    return ExplorerProfileResponse(user_id=UUID(row["user_id"]), **fields)


@router.get("/privacy", response_model=PrivacySettingsResponse)
async def get_privacy_settings(user: ExplorerUser) -> PrivacySettingsResponse:
    """Return explorer privacy settings."""
    row = await PostgresPrivacyRepository().get_privacy_settings(user.id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Privacy settings not found"
        )
    return PrivacySettingsResponse(**row)


@router.put("/privacy", response_model=PrivacySettingsResponse)
async def upsert_privacy_settings(
    payload: PrivacySettingsUpdateRequest,
    _: TripCreator,
    user: ExplorerUser,
) -> PrivacySettingsResponse:
    """Update explorer privacy settings."""
    row = await PostgresPrivacyRepository().upsert_privacy_settings(
        user.id,
        **payload.model_dump(exclude_unset=True),
    )
    return PrivacySettingsResponse(**row)


@router.post("/trips", status_code=status.HTTP_201_CREATED)
async def create_travel_plan(
    request: Request,
    payload: TravelPlanCreateRequest,
    _: TripCreator,
    user: ExplorerUser,
) -> dict:
    """Create a travel plan with destinations."""
    request_id = request_id_from(request)
    log_info(
        logger,
        "Travel plan create request received",
        request_id=request_id,
        user_id=user.id,
        title=payload.title,
    )
    plan = await PostgresTripRepository().create_travel_plan(
        user.id,
        title=payload.title,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_primary=payload.is_primary,
        destinations=[dest.model_dump() for dest in payload.destinations],
    )
    log_info(
        logger,
        "Travel plan created",
        request_id=request_id,
        user_id=user.id,
        plan_id=plan.get("id"),
    )
    return {"plan": dict(plan)}


@router.put("/location")
async def update_current_location(
    payload: CurrentLocationUpdateRequest,
    _: TripCreator,
    user: ExplorerUser,
) -> dict:
    """Update explorer current location."""
    row = await PostgresTripRepository().upsert_current_location(
        user.id,
        country_id=payload.country_id,
        state_id=payload.state_id,
        city_id=payload.city_id,
        custom_country_name=payload.custom_country_name,
        custom_state_name=payload.custom_state_name,
        custom_city_name=payload.custom_city_name,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    return {"location": dict(row)}


@router.get("/search", response_model=ExplorerSearchResponse, deprecated=True)
async def search_explorers_deprecated(
    request: Request,
    _: TripSearcher,
    user: ConnectorUser,
    destination_country: str = Query(..., min_length=2, max_length=2),
    q: str = Query(""),
    city_id: int | None = None,
    current_country: str | None = Query(None, min_length=2, max_length=2),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> ExplorerSearchResponse:
    """Deprecated: use GET /v1/connectors/search/explorers instead."""
    log_info(
        logger,
        "Deprecated explorer search alias invoked",
        request_id=request_id_from(request),
        viewer_id=user.id,
    )
    return await search_explorers_by_route(
        request=request,
        user=user,
        destination_country=destination_country,
        q=q,
        city_id=city_id,
        current_country=current_country,
        limit=limit,
        offset=offset,
    )
