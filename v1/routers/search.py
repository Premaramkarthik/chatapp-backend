"""Typesense-backed search routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.config.settings import settings
from core.logging.logger import get_logger, log_info
from domains.search.analytics.service import SearchAnalyticsService
from domains.search.filters import TravelerSearchFilters
from domains.search.recommendations.service import RecommendationService
from domains.search.service import SearchService
from domains.users.user import User
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.auth import require_capability
from v1.schemas.principal import KeycloakPrincipal
from v1.schemas.search import (
    GlobalSearchResponse,
    SearchCityHit,
    SearchCountryHit,
    SearchEventRequest,
    SearchEventResponse,
    SearchListResponse,
    SearchStateHit,
    SearchTravelerHit,
    SearchUserHit,
    SuggestionItem,
    SuggestionsResponse,
)
from v1.utils.base import TypesenseIntegrationError
from v1.utils.request_context import request_id_from
from workers.search_tasks import record_search_event

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/search", tags=["search"])

TripSearcher = Annotated[KeycloakPrincipal, Depends(require_capability("trip:join"))]


async def _authenticated_user(
    principal: Annotated[KeycloakPrincipal, Depends(require_capability("profile:update"))],
) -> User:
    """Resolve the local user row for search routes that need a Postgres user id."""
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


AuthenticatedUser = Annotated[User, Depends(_authenticated_user)]


def _search_service() -> SearchService:
    return SearchService()


def _analytics_service() -> SearchAnalyticsService:
    return SearchAnalyticsService()


@router.get("", response_model=GlobalSearchResponse)
async def global_search(
    request: Request,
    user: AuthenticatedUser,
    q: str = Query("", max_length=200),
    limit: int = Query(5, ge=1, le=20),
) -> GlobalSearchResponse:
    """Run grouped global search across users, travelers, and geo collections."""
    viewer_id = user.id
    try:
        raw = await _search_service().global_search(q=q, viewer_id=viewer_id, limit=limit)
    except TypesenseIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    if viewer_id and q.strip():
        await _analytics_service().remember_query(viewer_id, q)
    log_info(
        logger,
        "Global search completed",
        request_id=request_id_from(request),
        query_len=len(q),
        viewer_id=viewer_id,
    )
    return GlobalSearchResponse(
        users=[SearchUserHit.model_validate(doc) for doc in raw["users"]],
        travelers=[SearchTravelerHit.model_validate(doc) for doc in raw["travelers"]],
        cities=[SearchCityHit.model_validate(doc) for doc in raw["cities"]],
        countries=[SearchCountryHit.model_validate(doc) for doc in raw["countries"]],
        states=[SearchStateHit.model_validate(doc) for doc in raw["states"]],
        requests=raw.get("requests") or [],
    )


@router.get("/users", response_model=SearchListResponse)
async def search_users(
    request: Request,
    user: AuthenticatedUser,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
) -> SearchListResponse:
    """Search users with ranking and visibility filters."""
    try:
        raw = await _search_service().search_users(
            q=q,
            viewer_id=user.id,
            page=page,
            limit=limit,
        )
    except TypesenseIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    if q.strip():
        await _analytics_service().remember_query(user.id, q)
    hits = [hit.get("document") or {} for hit in raw.get("hits") or []]
    return SearchListResponse(hits=hits, total=raw.get("found") or 0, page=page, limit=limit)


@router.get("/travelers", response_model=SearchListResponse)
async def search_travelers(
    request: Request,
    _: TripSearcher,
    user: AuthenticatedUser,
    q: str = Query(""),
    from_city: str | None = None,
    to_city: str | None = None,
    from_country: str | None = Query(None, min_length=2, max_length=2),
    to_country: str | None = Query(None, min_length=2, max_length=2),
    verified: bool | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
) -> SearchListResponse:
    """Search travelers with route and visibility filters."""
    filters = TravelerSearchFilters(
        q=q,
        from_city=from_city,
        to_city=to_city,
        from_country=from_country,
        to_country=to_country,
        verified=verified,
        page=page,
        limit=limit,
    )
    try:
        raw = await _search_service().search_travelers(filters, viewer_id=user.id)
    except TypesenseIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    if q.strip():
        await _analytics_service().remember_query(user.id, q)
    hits = [hit.get("document") or {} for hit in raw.get("hits") or []]
    return SearchListResponse(hits=hits, total=raw.get("found") or 0, page=page, limit=limit)


@router.get("/cities", response_model=SearchListResponse)
async def search_cities(
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=50),
) -> SearchListResponse:
    """Search cities for autocomplete."""
    try:
        raw = await _search_service().search_cities(q=q, limit=limit)
    except TypesenseIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    hits = [hit.get("document") or {} for hit in raw.get("hits") or []]
    return SearchListResponse(hits=hits, total=raw.get("found") or 0, page=1, limit=limit)


@router.get("/countries", response_model=SearchListResponse)
async def search_countries(
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=50),
) -> SearchListResponse:
    """Search countries for autocomplete."""
    try:
        raw = await _search_service().search_countries(q=q, limit=limit)
    except TypesenseIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    hits = [hit.get("document") or {} for hit in raw.get("hits") or []]
    return SearchListResponse(hits=hits, total=raw.get("found") or 0, page=1, limit=limit)


@router.get("/states", response_model=SearchListResponse)
async def search_states(
    q: str = Query("", max_length=100),
    country_iso2: str | None = Query(None, min_length=2, max_length=2),
    limit: int = Query(20, ge=1, le=50),
) -> SearchListResponse:
    """Search states for autocomplete."""
    try:
        raw = await _search_service().search_states(
            q=q,
            country_iso2=country_iso2,
            limit=limit,
        )
    except TypesenseIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    hits = [hit.get("document") or {} for hit in raw.get("hits") or []]
    return SearchListResponse(hits=hits, total=raw.get("found") or 0, page=1, limit=limit)


@router.get("/suggestions/popular", response_model=SuggestionsResponse)
async def popular_suggestions(limit: int = Query(10, ge=1, le=20)) -> SuggestionsResponse:
    """Return popular search suggestions."""
    if settings.typesense.enabled:
        raw = await _search_service().search_popular_searches(limit=limit)
        hits = [hit.get("document") or {} for hit in raw.get("hits") or []]
        if hits:
            return SuggestionsResponse(
                items=[SuggestionItem.model_validate(doc) for doc in hits],
            )
    items = await _analytics_service().popular_queries(limit=limit)
    return SuggestionsResponse(items=[SuggestionItem.model_validate(item) for item in items])


@router.get("/suggestions/recent", response_model=SuggestionsResponse)
async def recent_suggestions(user: AuthenticatedUser) -> SuggestionsResponse:
    """Return recent searches for the authenticated user."""
    queries = await _analytics_service().recent_searches(user.id)
    return SuggestionsResponse(
        items=[SuggestionItem(id=query, label=query, kind="query", score=0.0) for query in queries],
    )


@router.get("/suggestions/routes", response_model=SuggestionsResponse)
async def route_suggestions(limit: int = Query(10, ge=1, le=20)) -> SuggestionsResponse:
    """Return trending traveler route suggestions."""
    items = await _search_service().search_route_suggestions(limit=limit)
    return SuggestionsResponse(items=[SuggestionItem.model_validate(item) for item in items])


@router.get("/suggestions/people", response_model=SuggestionsResponse)
async def people_suggestions(
    user: AuthenticatedUser,
    limit: int = Query(10, ge=1, le=20),
) -> SuggestionsResponse:
    """Return suggested people (stub until recommendation scoring ships)."""
    items = await RecommendationService().suggested_people(user.id, limit=limit)
    return SuggestionsResponse(items=[SuggestionItem.model_validate(item) for item in items])


@router.post("/events", response_model=SearchEventResponse, status_code=status.HTTP_202_ACCEPTED)
async def record_search_analytics_event(
    payload: SearchEventRequest,
    user: AuthenticatedUser,
) -> SearchEventResponse:
    """Record a search click/impression analytics event."""
    if settings.typesense.enabled:
        record_search_event.send(
            user_id=user.id,
            query=payload.query,
            result_type=payload.result_type,
            result_id=payload.result_id,
            clicked=payload.clicked,
        )
        return SearchEventResponse(recorded=True)
    row = await _analytics_service().record_event(
        user_id=user.id,
        query=payload.query,
        result_type=payload.result_type,
        result_id=payload.result_id,
        clicked=payload.clicked,
    )
    return SearchEventResponse(recorded=True, event_id=UUID(row["id"]))
