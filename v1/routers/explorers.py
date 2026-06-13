"""Explorer profile, trips, location, and search routes."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.logging.logger import get_logger, log_info
from domains.auth.security import hash_secret
from domains.geo.display import enrich_home_location
from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from infrastructure.database.repositories.explorers import PostgresExplorerRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.database.repositories.trips import PostgresTripRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from infrastructure.meilisearch.client import get_meilisearch_client
from infrastructure.meilisearch.explorer_search import ExplorerSearchQuery, search_explorers
from v1.dependencies.auth import get_current_principal, require_capability
from v1.schemas.explorers import (
    CurrentLocationUpdateRequest,
    ExplorerProfileResponse,
    ExplorerProfileUpdateRequest,
    ExplorerSearchResponse,
    ExplorerSearchResult,
    TravelPlanCreateRequest,
)
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.request_context import request_id_from

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/explorers", tags=["explorers"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
TripCreator = Annotated[KeycloakPrincipal, Depends(require_capability("trip:create"))]
TripSearcher = Annotated[KeycloakPrincipal, Depends(require_capability("trip:join"))]


async def _local_user_id(principal: KeycloakPrincipal) -> str:
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.id


def _require_explorer_mode(account_mode: str | None) -> None:
    if account_mode != "explorer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Explorer profile requires account_mode explorer",
        )


@router.get("/profile", response_model=ExplorerProfileResponse)
async def get_explorer_profile(principal: CurrentPrincipal) -> ExplorerProfileResponse:
    """Return the authenticated user's explorer profile."""
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _require_explorer_mode(user.account_mode)
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
    principal: CurrentPrincipal,
) -> ExplorerProfileResponse:
    """Create or update explorer profile and rebuild discovery snapshot."""
    request_id = request_id_from(request)
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _require_explorer_mode(user.account_mode)
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


@router.post("/trips", status_code=status.HTTP_201_CREATED)
async def create_travel_plan(
    request: Request,
    payload: TravelPlanCreateRequest,
    _: TripCreator,
    principal: CurrentPrincipal,
) -> dict:
    """Create a travel plan with destinations."""
    request_id = request_id_from(request)
    user_id = await _local_user_id(principal)
    log_info(
        logger,
        "Travel plan create request received",
        request_id=request_id,
        user_id=user_id,
        title=payload.title,
    )
    plan = await PostgresTripRepository().create_travel_plan(
        user_id,
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
        user_id=user_id,
        plan_id=plan.get("id"),
    )
    return {"plan": dict(plan)}


@router.put("/location")
async def update_current_location(
    payload: CurrentLocationUpdateRequest,
    _: TripCreator,
    principal: CurrentPrincipal,
) -> dict:
    """Update explorer current location."""
    user_id = await _local_user_id(principal)
    row = await PostgresTripRepository().upsert_current_location(
        user_id,
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


@router.get("/search", response_model=ExplorerSearchResponse)
async def search_explorers_route(
    request: Request,
    _: TripSearcher,
    principal: CurrentPrincipal,
    destination_country: str = Query(..., min_length=2, max_length=2),
    q: str = Query(""),
    city_id: int | None = None,
    current_country: str | None = Query(None, min_length=2, max_length=2),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> ExplorerSearchResponse:
    """Search discoverable explorers by destination country (Meilisearch + hydrate)."""
    from core.config.settings import settings

    request_id = request_id_from(request)
    query_hash = hash_secret(f"{destination_country}:{q}:{city_id}:{current_country}")[:16]
    viewer_id = await _local_user_id(principal)
    log_info(
        logger,
        "Explorer search request received",
        request_id=request_id,
        viewer_id=viewer_id,
        destination_country=destination_country.upper(),
        query_hash=query_hash,
    )
    discovery = PostgresDiscoveryRepository()
    hits: list[ExplorerSearchResult] = []
    total = 0

    if settings.meilisearch.enabled:
        query = ExplorerSearchQuery(
            destination_country=destination_country.upper(),
            q=q,
            city_id=str(city_id) if city_id is not None else None,
            current_country=current_country.upper() if current_country else None,
            limit=limit,
            offset=offset,
        )
        client = get_meilisearch_client()
        raw = await asyncio.to_thread(
            search_explorers,
            client,
            settings.meilisearch.explorer_index,
            query,
        )
        total = int(raw.get("estimatedTotalHits") or raw.get("totalHits") or 0)
        meili_hits = raw.get("hits") or []
        ids = [str(item["id"]) for item in meili_hits]
        rows = await discovery.fetch_public_by_ids(ids)
        row_by_id = {str(row["user_id"]): row for row in rows}
        for item in meili_hits:
            user_id = str(item["id"])
            if user_id == viewer_id:
                continue
            if await PostgresMatchingRepository().is_blocked(viewer_id, user_id):
                continue
            row = row_by_id.get(user_id)
            if row is None:
                continue
            hits.append(_snapshot_to_search_result(row))
    else:
        rows = await discovery.list_postgres_search(
            destination_country=destination_country,
            current_country=current_country,
            viewer_id=viewer_id,
            limit=limit,
            offset=offset,
        )
        total = len(rows)
        hits = [_snapshot_to_search_result(row) for row in rows if str(row["user_id"]) != viewer_id]

    log_info(
        logger,
        "Explorer search completed",
        request_id=request_id,
        viewer_id=viewer_id,
        hit_count=len(hits),
        total=total,
    )
    return ExplorerSearchResponse(hits=hits, total=total, limit=limit, offset=offset)


def _snapshot_to_search_result(row: dict) -> ExplorerSearchResult:
    return ExplorerSearchResult(
        user_id=UUID(str(row["user_id"])),
        display_name=row.get("display_name"),
        headline=row.get("headline"),
        avatar_url=row.get("avatar_url"),
        destination_country_iso=row.get("destination_country_iso"),
        destination_city_name=row.get("destination_city_name"),
        current_country_iso=row.get("current_country_iso"),
        languages=list(row.get("languages") or []),
        interests=list(row.get("interests") or []),
        connection_availability=row.get("connection_availability") or "open",
        last_active_at=row.get("last_active_at"),
    )
