"""Connector-scoped search routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
from domains.auth.security import hash_secret
from domains.search.filters import TravelerSearchFilters
from domains.search.service import SearchService
from domains.search.username import slugify_username
from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from v1.dependencies.account_mode import ConnectorUser
from v1.dependencies.auth import require_capability
from v1.schemas.connector_search import (
    ConnectorUserSearchHit,
    ConnectorUserSearchResponse,
    ExplorerSearchResponse,
    ExplorerSearchResult,
)
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import TypesenseIntegrationError
from v1.utils.request_context import request_id_from

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/connectors/search", tags=["connectors"])
TripSearcher = Annotated[KeycloakPrincipal, Depends(require_capability("trip:join"))]


def snapshot_to_explorer_result(row: dict) -> ExplorerSearchResult:
    """Map a discovery snapshot row to an explorer search card."""
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


async def search_explorers_by_route(
    *,
    request: Request,
    user: ConnectorUser,
    destination_country: str,
    q: str = "",
    city_id: int | None = None,
    current_country: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ExplorerSearchResponse:
    """Search discoverable explorers by destination country."""
    request_id = request_id_from(request)
    query_hash = hash_secret(f"{destination_country}:{q}:{city_id}:{current_country}")[:16]
    viewer_id = user.id
    log_info(
        logger,
        "Connector explorer route search received",
        request_id=request_id,
        viewer_id=viewer_id,
        destination_country=destination_country.upper(),
        query_hash=query_hash,
    )
    discovery = PostgresDiscoveryRepository()
    hits: list[ExplorerSearchResult] = []
    total = 0
    country = destination_country.upper()

    if settings.typesense.enabled and q.strip():
        page = (offset // limit) + 1
        filters = TravelerSearchFilters(
            destination_country=country,
            q=q,
            city_id=str(city_id) if city_id is not None else None,
            current_country=current_country.upper() if current_country else None,
            limit=limit,
            page=page,
            offset=offset,
        )
        try:
            raw = await SearchService().search_travelers(filters, viewer_id=viewer_id)
        except TypesenseIntegrationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
        total = int(raw.get("found") or 0)
        ts_hits = raw.get("hits") or []
        ids = [
            str((hit.get("document") or {}).get("user_id") or hit.get("document", {}).get("id"))
            for hit in ts_hits
        ]
        ids = [item for item in ids if item]
        rows = await discovery.fetch_public_by_ids(ids)
        row_by_id = {str(row["user_id"]): row for row in rows}
        matching = PostgresMatchingRepository()
        for hit in ts_hits:
            doc = hit.get("document") or {}
            hit_user_id = str(doc.get("user_id") or doc.get("id"))
            if not hit_user_id or hit_user_id == viewer_id:
                continue
            if await matching.is_blocked(viewer_id, hit_user_id):
                continue
            row = row_by_id.get(hit_user_id)
            if row is None:
                continue
            hits.append(snapshot_to_explorer_result(row))
        total = len(hits)
    else:
        rows, total = await discovery.list_discoverable_explorers(
            destination_country=country,
            q=q,
            current_country=current_country,
            viewer_id=viewer_id,
            limit=limit,
            offset=offset,
        )
        hits = [snapshot_to_explorer_result(row) for row in rows]

    log_info(
        logger,
        "Connector explorer route search completed",
        request_id=request_id,
        viewer_id=viewer_id,
        hit_count=len(hits),
        total=total,
    )
    return ExplorerSearchResponse(hits=hits, total=total, limit=limit, offset=offset)


@router.get("/explorers", response_model=ExplorerSearchResponse)
async def connector_search_explorers_route(
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
    """Search discoverable explorers by destination country."""
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


async def _connector_username_search_postgres(
    *,
    q: str,
    viewer_id: str,
    page: int,
    limit: int,
) -> ConnectorUserSearchResponse:
    """Postgres fallback for explorer username search."""
    offset = (page - 1) * limit
    rows, total = await PostgresDiscoveryRepository().search_by_username(
        q=q,
        viewer_id=viewer_id,
        limit=limit,
        offset=offset,
    )
    hits: list[ConnectorUserSearchHit] = []
    for row in rows:
        display_name = row.get("display_name")
        home_label = row.get("home_country_iso")
        hits.append(
            ConnectorUserSearchHit(
                user_id=UUID(str(row["user_id"])),
                display_name=display_name,
                username=slugify_username(display_name),
                avatar_url=row.get("avatar_url"),
                home_label=str(home_label) if home_label else None,
                role="explorer",
                headline=row.get("headline"),
                destination_country_iso=row.get("destination_country_iso"),
                connection_availability=row.get("connection_availability") or "open",
            )
        )
    return ConnectorUserSearchResponse(hits=hits, total=total, page=page, limit=limit)


@router.get("/users", response_model=ConnectorUserSearchResponse)
async def connector_search_users_route(
    request: Request,
    _: TripSearcher,
    user: ConnectorUser,
    q: str = Query(..., min_length=2, max_length=200),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
) -> ConnectorUserSearchResponse:
    """Search explorers by username or display name."""
    request_id = request_id_from(request)
    viewer_id = user.id
    log_info(
        logger,
        "Connector username search received",
        request_id=request_id,
        viewer_id=viewer_id,
        query_len=len(q),
    )
    use_postgres = not settings.typesense.enabled
    raw: dict | None = None
    if settings.typesense.enabled:
        try:
            raw = await SearchService().search_users(
                q=q,
                viewer_id=viewer_id,
                page=page,
                limit=limit,
                role="explorer",
            )
        except TypesenseIntegrationError as exc:
            log_warning(
                logger,
                "Connector username search falling back to postgres",
                request_id=request_id,
                reason=str(exc),
            )
            use_postgres = True

    if use_postgres:
        response = await _connector_username_search_postgres(
            q=q,
            viewer_id=viewer_id,
            page=page,
            limit=limit,
        )
        log_info(
            logger,
            "Connector username search completed",
            request_id=request_id,
            viewer_id=viewer_id,
            hit_count=len(response.hits),
            source="postgres",
        )
        return response

    ts_hits = raw.get("hits") or [] if raw else []
    ids = [str((hit.get("document") or {}).get("id")) for hit in ts_hits]
    ids = [item for item in ids if item]
    rows = await PostgresDiscoveryRepository().fetch_public_by_ids(ids)
    row_by_id = {str(row["user_id"]): row for row in rows}
    matching = PostgresMatchingRepository()
    hits: list[ConnectorUserSearchHit] = []

    for hit in ts_hits:
        doc = hit.get("document") or {}
        hit_user_id = str(doc.get("id") or "")
        if not hit_user_id or hit_user_id == viewer_id:
            continue
        if await matching.is_blocked(viewer_id, hit_user_id):
            continue
        snapshot = row_by_id.get(hit_user_id)
        home_parts = [doc.get("city"), doc.get("country")]
        home_label = ", ".join(part for part in home_parts if part) or None
        hits.append(
            ConnectorUserSearchHit(
                user_id=UUID(hit_user_id),
                display_name=snapshot.get("display_name") if snapshot else doc.get("full_name"),
                username=doc.get("username"),
                avatar_url=snapshot.get("avatar_url") if snapshot else doc.get("profile_photo"),
                home_label=home_label,
                role=doc.get("role"),
                headline=snapshot.get("headline") if snapshot else None,
                destination_country_iso=(
                    snapshot.get("destination_country_iso") if snapshot else None
                ),
                connection_availability=(
                    snapshot.get("connection_availability") if snapshot else "open"
                )
                or "open",
            )
        )

    log_info(
        logger,
        "Connector username search completed",
        request_id=request_id,
        viewer_id=viewer_id,
        hit_count=len(hits),
        source="typesense",
    )
    return ConnectorUserSearchResponse(
        hits=hits,
        total=int(raw.get("found") or len(hits)),
        page=page,
        limit=limit,
    )
