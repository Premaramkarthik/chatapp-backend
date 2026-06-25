"""Explorer-scoped search routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.config.settings import settings
from core.logging.logger import get_logger, log_info, log_warning
from domains.search.service import SearchService
from domains.search.username import slugify_username
from infrastructure.database.repositories.connector_discovery import (
    PostgresConnectorDiscoveryRepository,
)
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from v1.dependencies.account_mode import ExplorerUser
from v1.dependencies.auth import require_capability
from v1.schemas.explorer_search import (
    ConnectorSearchResponse,
    ConnectorSearchResult,
    ExplorerUserSearchHit,
    ExplorerUserSearchResponse,
)
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.base import TypesenseIntegrationError
from v1.utils.request_context import request_id_from

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/explorers/search", tags=["explorers"])
TripCreator = Annotated[KeycloakPrincipal, Depends(require_capability("trip:create"))]


def connector_row_to_result(row: dict) -> ConnectorSearchResult:
    """Map a connector discovery row to a search card."""
    preferred = row.get("preferred_destination_countries") or []
    return ConnectorSearchResult(
        user_id=UUID(str(row["user_id"])),
        display_name=row.get("display_name"),
        bio=row.get("bio"),
        avatar_url=row.get("avatar_url"),
        home_country_label=row.get("home_country_label"),
        home_city_label=row.get("home_city_label"),
        preferred_destination_countries=[str(c).upper() for c in preferred],
        last_active_at=row.get("last_active_at"),
    )


@router.get("/connectors", response_model=ConnectorSearchResponse)
async def explorer_search_connectors_route(
    request: Request,
    _: TripCreator,
    user: ExplorerUser,
    destination_country: str = Query(..., min_length=2, max_length=2),
    q: str = Query(""),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> ConnectorSearchResponse:
    """Search discoverable connectors by destination country and optional keyword."""
    request_id = request_id_from(request)
    viewer_id = user.id
    country = destination_country.upper()
    log_info(
        logger,
        "Explorer connector route search received",
        request_id=request_id,
        viewer_id=viewer_id,
        destination_country=country,
    )
    discovery = PostgresConnectorDiscoveryRepository()
    hits: list[ConnectorSearchResult] = []
    total = 0

    if settings.typesense.enabled and q.strip():
        page = (offset // limit) + 1
        try:
            raw = await SearchService().search_users(
                q=q,
                viewer_id=viewer_id,
                page=page,
                limit=limit,
                role="connector",
            )
        except TypesenseIntegrationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
        total = int(raw.get("found") or 0)
        ts_hits = raw.get("hits") or []
        ids = [str((hit.get("document") or {}).get("id")) for hit in ts_hits]
        ids = [item for item in ids if item]
        rows = await discovery.fetch_public_by_ids(ids)
        row_by_id = {str(row["user_id"]): row for row in rows}
        matching = PostgresMatchingRepository()
        for hit in ts_hits:
            doc = hit.get("document") or {}
            hit_user_id = str(doc.get("id") or "")
            if not hit_user_id or hit_user_id == viewer_id:
                continue
            if await matching.is_blocked(viewer_id, hit_user_id):
                continue
            row = row_by_id.get(hit_user_id)
            if row is None:
                continue
            preferred = row.get("preferred_destination_countries") or []
            home_country = (row.get("home_country_label") or "").upper()
            if country not in [str(c).upper() for c in preferred] and home_country != country:
                continue
            hits.append(connector_row_to_result(row))
        total = len(hits)
    else:
        rows, total = await discovery.list_discoverable_connectors(
            destination_country=country,
            q=q,
            viewer_id=viewer_id,
            limit=limit,
            offset=offset,
        )
        hits = [connector_row_to_result(row) for row in rows]

    log_info(
        logger,
        "Explorer connector route search completed",
        request_id=request_id,
        viewer_id=viewer_id,
        hit_count=len(hits),
        total=total,
    )
    return ConnectorSearchResponse(hits=hits, total=total, limit=limit, offset=offset)


async def _explorer_username_search_postgres(
    *,
    q: str,
    viewer_id: str,
    page: int,
    limit: int,
) -> ExplorerUserSearchResponse:
    """Postgres fallback for connector username search."""
    offset = (page - 1) * limit
    rows, total = await PostgresConnectorDiscoveryRepository().search_by_username(
        q=q,
        viewer_id=viewer_id,
        limit=limit,
        offset=offset,
    )
    hits: list[ExplorerUserSearchHit] = []
    for row in rows:
        home_parts = [row.get("home_city_label"), row.get("home_country_label")]
        home_label = ", ".join(part for part in home_parts if part) or None
        preferred = row.get("preferred_destination_countries") or []
        display_name = row.get("display_name")
        hits.append(
            ExplorerUserSearchHit(
                user_id=UUID(str(row["user_id"])),
                display_name=display_name,
                username=slugify_username(display_name),
                avatar_url=row.get("avatar_url"),
                home_label=home_label,
                role="connector",
                bio=row.get("bio"),
                preferred_destination_countries=[str(c).upper() for c in preferred],
            )
        )
    return ExplorerUserSearchResponse(hits=hits, total=total, page=page, limit=limit)


@router.get("/users", response_model=ExplorerUserSearchResponse)
async def explorer_search_users_route(
    request: Request,
    _: TripCreator,
    user: ExplorerUser,
    q: str = Query(..., min_length=2, max_length=200),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
) -> ExplorerUserSearchResponse:
    """Search connectors by username or display name."""
    request_id = request_id_from(request)
    viewer_id = user.id
    log_info(
        logger,
        "Explorer username search received",
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
                role="connector",
            )
        except TypesenseIntegrationError as exc:
            log_warning(
                logger,
                "Explorer username search falling back to postgres",
                request_id=request_id,
                reason=str(exc),
            )
            use_postgres = True

    if use_postgres:
        response = await _explorer_username_search_postgres(
            q=q,
            viewer_id=viewer_id,
            page=page,
            limit=limit,
        )
        log_info(
            logger,
            "Explorer username search completed",
            request_id=request_id,
            viewer_id=viewer_id,
            hit_count=len(response.hits),
            source="postgres",
        )
        return response

    ts_hits = raw.get("hits") or [] if raw else []
    ids = [str((hit.get("document") or {}).get("id")) for hit in ts_hits]
    ids = [item for item in ids if item]
    rows = await PostgresConnectorDiscoveryRepository().fetch_public_by_ids(ids)
    row_by_id = {str(row["user_id"]): row for row in rows}
    matching = PostgresMatchingRepository()
    hits: list[ExplorerUserSearchHit] = []

    for hit in ts_hits:
        doc = hit.get("document") or {}
        hit_user_id = str(doc.get("id") or "")
        if not hit_user_id or hit_user_id == viewer_id:
            continue
        if await matching.is_blocked(viewer_id, hit_user_id):
            continue
        snapshot = row_by_id.get(hit_user_id)
        if snapshot is None:
            continue
        home_parts = [
            snapshot.get("home_city_label"),
            snapshot.get("home_country_label"),
        ]
        home_label = ", ".join(part for part in home_parts if part) or None
        preferred = snapshot.get("preferred_destination_countries") or []
        hits.append(
            ExplorerUserSearchHit(
                user_id=UUID(hit_user_id),
                display_name=snapshot.get("display_name") or doc.get("full_name"),
                username=doc.get("username"),
                avatar_url=snapshot.get("avatar_url") or doc.get("profile_photo"),
                home_label=home_label,
                role=doc.get("role"),
                bio=snapshot.get("bio"),
                preferred_destination_countries=[str(c).upper() for c in preferred],
            )
        )

    log_info(
        logger,
        "Explorer username search completed",
        request_id=request_id,
        viewer_id=viewer_id,
        hit_count=len(hits),
        source="typesense",
    )
    return ExplorerUserSearchResponse(
        hits=hits,
        total=int(raw.get("found") or len(hits)),
        page=page,
        limit=limit,
    )
