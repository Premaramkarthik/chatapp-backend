"""Traveler profile, trips, location, and search routes."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.database.repositories.travelers import PostgresTravelerRepository
from infrastructure.database.repositories.trips import PostgresTripRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from infrastructure.meilisearch.client import get_meilisearch_client
from infrastructure.meilisearch.traveler_search import TravelerSearchQuery, search_travelers
from v1.dependencies.auth import get_current_principal, require_capability
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.travelers import (
    CurrentLocationUpdateRequest,
    TravelerProfileResponse,
    TravelerProfileUpdateRequest,
    TravelerSearchResponse,
    TravelerSearchResult,
    TravelPlanCreateRequest,
)

router = APIRouter(prefix="/v1/travelers", tags=["travelers"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
TripCreator = Annotated[KeycloakPrincipal, Depends(require_capability("trip:create"))]
TripSearcher = Annotated[KeycloakPrincipal, Depends(require_capability("trip:join"))]


async def _local_user_id(principal: KeycloakPrincipal) -> str:
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.id


def _require_traveler_mode(account_mode: str) -> None:
    if account_mode not in ("traveler", "both"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Traveler profile requires account_mode traveler or both",
        )


@router.get("/profile", response_model=TravelerProfileResponse)
async def get_traveler_profile(principal: CurrentPrincipal) -> TravelerProfileResponse:
    """Return the authenticated user's traveler profile."""
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _require_traveler_mode(user.account_mode)
    row = await PostgresTravelerRepository().get_traveler_profile(user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    fields = {k: v for k, v in row.items() if k != "user_id"}
    return TravelerProfileResponse(user_id=UUID(row["user_id"]), **fields)


@router.put("/profile", response_model=TravelerProfileResponse)
async def upsert_traveler_profile(
    payload: TravelerProfileUpdateRequest,
    _: TripCreator,
    principal: CurrentPrincipal,
) -> TravelerProfileResponse:
    """Create or update traveler profile and rebuild discovery snapshot."""
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _require_traveler_mode(user.account_mode)
    row = await PostgresTravelerRepository().upsert_traveler_profile(
        user.id,
        **payload.model_dump(exclude_unset=True),
    )
    fields = {k: v for k, v in row.items() if k != "user_id"}
    return TravelerProfileResponse(user_id=UUID(row["user_id"]), **fields)


@router.post("/trips", status_code=status.HTTP_201_CREATED)
async def create_travel_plan(
    payload: TravelPlanCreateRequest,
    _: TripCreator,
    principal: CurrentPrincipal,
) -> dict:
    """Create a travel plan with destinations."""
    user_id = await _local_user_id(principal)
    plan = await PostgresTripRepository().create_travel_plan(
        user_id,
        title=payload.title,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_primary=payload.is_primary,
        destinations=[dest.model_dump() for dest in payload.destinations],
    )
    return {"plan": dict(plan)}


@router.put("/location")
async def update_current_location(
    payload: CurrentLocationUpdateRequest,
    _: TripCreator,
    principal: CurrentPrincipal,
) -> dict:
    """Update traveler current location."""
    user_id = await _local_user_id(principal)
    row = await PostgresTripRepository().upsert_current_location(
        user_id,
        country_iso=payload.country_iso,
        city_id=str(payload.city_id) if payload.city_id else None,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    return {"location": dict(row)}


@router.get("/search", response_model=TravelerSearchResponse)
async def search_travelers_route(
    _: TripSearcher,
    principal: CurrentPrincipal,
    destination_country: str = Query(..., min_length=2, max_length=2),
    q: str = Query(""),
    city_id: UUID | None = None,
    current_country: str | None = Query(None, min_length=2, max_length=2),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> TravelerSearchResponse:
    """Search discoverable travelers by destination country (Meilisearch + hydrate)."""
    from core.config.settings import settings

    viewer_id = await _local_user_id(principal)
    discovery = PostgresDiscoveryRepository()
    hits: list[TravelerSearchResult] = []
    total = 0

    if settings.meilisearch.enabled:
        query = TravelerSearchQuery(
            destination_country=destination_country.upper(),
            q=q,
            city_id=str(city_id) if city_id else None,
            current_country=current_country.upper() if current_country else None,
            limit=limit,
            offset=offset,
        )
        client = get_meilisearch_client()
        raw = await asyncio.to_thread(
            search_travelers,
            client,
            settings.meilisearch.traveler_index,
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

    return TravelerSearchResponse(hits=hits, total=total, limit=limit, offset=offset)


def _snapshot_to_search_result(row: dict) -> TravelerSearchResult:
    return TravelerSearchResult(
        user_id=UUID(str(row["user_id"])),
        display_name=row.get("display_name"),
        headline=row.get("headline"),
        avatar_url=row.get("avatar_url"),
        destination_country_iso=row["destination_country_iso"],
        destination_city_name=row.get("destination_city_name"),
        current_country_iso=row.get("current_country_iso"),
        languages=list(row.get("languages") or []),
        interests=list(row.get("interests") or []),
        connection_availability=row.get("connection_availability") or "open",
        last_active_at=row.get("last_active_at"),
    )
