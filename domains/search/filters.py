"""Viewer-aware Typesense filter builders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from infrastructure.database.connection import fetch
from infrastructure.database.repositories.matching import PostgresMatchingRepository


@dataclass(frozen=True)
class TravelerSearchFilters:
    """Parameters for destination-country-first traveler search."""

    destination_country: str | None = None
    q: str = ""
    city_id: str | None = None
    current_country: str | None = None
    from_city: str | None = None
    to_city: str | None = None
    from_country: str | None = None
    to_country: str | None = None
    verified: bool | None = None
    trip_active_on: date | None = None
    limit: int = 20
    page: int = 1
    offset: int = 0


async def load_block_exclusions(viewer_id: str | None) -> list[str]:
    """Return user ids that must be excluded for a viewer."""
    if not viewer_id:
        return []
    matching = PostgresMatchingRepository()
    blocked_by_viewer = await matching.list_blocks(viewer_id)
    excluded = {str(row["blocked_id"]) for row in blocked_by_viewer}
    rows = await fetch(
        """
        SELECT blocker_id::text AS blocker_id
        FROM user_blocks
        WHERE blocked_id = $1::uuid
        """,
        viewer_id,
    )
    excluded.update(str(row["blocker_id"]) for row in rows)
    excluded.discard(viewer_id)
    return sorted(excluded)


def build_viewer_filters(
    viewer_id: str | None,
    blocked_ids: list[str],
    *,
    id_field: str = "id",
) -> str:
    """Build mandatory visibility and block exclusion filters."""
    parts = ["is_searchable:=true"]
    if viewer_id:
        parts.append(f"{id_field}:!={viewer_id}")
    for blocked_id in blocked_ids:
        parts.append(f"{id_field}:!={blocked_id}")
    return " && ".join(parts)


def build_traveler_filters(filters: TravelerSearchFilters) -> str:
    """Build traveler-specific Typesense filter_by clauses."""
    parts: list[str] = []
    to_country = (filters.to_country or filters.destination_country or "").upper()
    if to_country:
        parts.append(f"to_country:={to_country}")
    from_country = (filters.from_country or filters.current_country or "").upper()
    if from_country:
        parts.append(f"from_country:={from_country}")
    if filters.city_id:
        parts.append(f"to_city:={filters.city_id}")
    if filters.from_city:
        parts.append(f"from_city:={filters.from_city}")
    if filters.to_city:
        parts.append(f"to_city:={filters.to_city}")
    if filters.verified is True:
        parts.append("verified:=true")
    if filters.trip_active_on:
        ts = int(datetime.combine(filters.trip_active_on, datetime.min.time()).timestamp())
        parts.append(f"departure_date:>={ts}")
    return " && ".join(parts) if parts else ""


def combine_filters(*clauses: str) -> str:
    """Join non-empty filter clauses with &&."""
    parts = [clause for clause in clauses if clause]
    return " && ".join(parts)


def build_role_filter(role: str | None) -> str:
    """Build account-mode filter for user collection searches."""
    if not role:
        return ""
    return f"role:={role.strip().lower()}"
