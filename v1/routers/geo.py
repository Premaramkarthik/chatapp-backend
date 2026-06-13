"""Read-only geo autocomplete routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from domains.geo.service import GeoService
from v1.schemas.geo import CityItem, CountryItem, GeoListResponse, StateItem

router = APIRouter(prefix="/v1/geo", tags=["geo"])


def _geo_service() -> GeoService:
    return GeoService()


@router.get("/countries", response_model=GeoListResponse)
async def search_countries(
    search: str = Query("", max_length=100),
    limit: int | None = Query(None, ge=1, le=5000),
) -> GeoListResponse:
    """Autocomplete countries by name or ISO code.
    Empty search returns all countries (up to list limit)."""
    rows = await _geo_service().search_countries(search, limit=limit)
    items = [CountryItem.model_validate(row) for row in rows]
    return GeoListResponse(items=items, count=len(items))


@router.get("/states", response_model=GeoListResponse)
async def search_states(
    country_id: int = Query(..., ge=1),
    search: str = Query("", max_length=100),
    limit: int | None = Query(None, ge=1, le=5000),
) -> GeoListResponse:
    """Autocomplete states for a country.
    Empty search returns all states for the country."""
    rows = await _geo_service().search_states(country_id, search, limit=limit)
    items = [StateItem.model_validate(row) for row in rows]
    return GeoListResponse(items=items, count=len(items))


@router.get("/cities", response_model=GeoListResponse)
async def search_cities(
    state_id: int = Query(..., ge=1),
    search: str = Query("", max_length=100),
    limit: int | None = Query(None, ge=1, le=5000),
) -> GeoListResponse:
    """Autocomplete cities for a state.
    Empty search returns all cities for the state."""
    rows = await _geo_service().search_cities(state_id, search, limit=limit)
    items = [CityItem.model_validate(row) for row in rows]
    return GeoListResponse(items=items, count=len(items))
