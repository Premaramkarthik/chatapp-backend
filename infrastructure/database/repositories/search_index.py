"""Read-only queries for bulk Typesense reindex."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from infrastructure.database.connection import fetch


class SearchIndexRepository:
    """Stream Postgres rows for search index rebuilds."""

    async def stream_users(self, *, batch_size: int = 500) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield user rows enriched for user collection indexing."""
        offset = 0
        while True:
            rows = await fetch(
                """
                SELECT
                    u.id,
                    u.display_name,
                    u.account_mode,
                    u.email_verified,
                    u.status,
                    u.onboarding_completed_at,
                    u.created_at,
                    u.updated_at,
                    ep.avatar_url AS avatar_url,
                    COALESCE(ep.visibility, 'discoverable') AS visibility,
                    COALESCE(ups.allow_search_discovery, true) AS allow_search_discovery,
                    COALESCE(ep.last_active_at, ep.updated_at, cp.updated_at) AS recent_activity_at,
                    ep.updated_at AS profile_updated_at,
                    gc.name AS home_country_name,
                    gs.name AS home_state_name,
                    gci.name AS home_city_name,
                    COALESCE(ep.custom_home_country_name, cp.custom_home_country_name)
                        AS custom_home_country_name,
                    COALESCE(ep.custom_home_state_name, cp.custom_home_state_name)
                        AS custom_home_state_name,
                    COALESCE(ep.custom_home_city_name, cp.custom_home_city_name)
                        AS custom_home_city_name,
                    (
                        SELECT COUNT(*)::int
                        FROM user_connections c
                        WHERE c.status = 'active'
                          AND (c.user_a_id = u.id OR c.user_b_id = u.id)
                    ) AS connections_count,
                    0::float AS search_popularity
                FROM users u
                LEFT JOIN explorer_profiles ep ON ep.user_id = u.id
                LEFT JOIN connector_profiles cp ON cp.user_id = u.id
                LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
                LEFT JOIN geo_countries gc
                    ON gc.id = COALESCE(ep.home_country_id, cp.home_country_id)
                LEFT JOIN geo_states gs ON gs.id = COALESCE(ep.home_state_id, cp.home_state_id)
                LEFT JOIN geo_cities gci ON gci.id = COALESCE(ep.home_city_id, cp.home_city_id)
                ORDER BY u.created_at
                LIMIT $1 OFFSET $2
                """,
                batch_size,
                offset,
            )
            if not rows:
                break
            yield [dict(row) for row in rows]
            if len(rows) < batch_size:
                break
            offset += batch_size

    async def stream_travelers(
        self,
        *,
        batch_size: int = 500,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield discovery snapshot rows enriched with user flags."""
        offset = 0
        while True:
            rows = await fetch(
                """
                SELECT
                    s.*,
                    u.email_verified,
                    (u.onboarding_completed_at IS NOT NULL) AS profile_completed
                FROM explorer_discovery_snapshots s
                JOIN users u ON u.id = s.user_id
                ORDER BY s.user_id
                LIMIT $1 OFFSET $2
                """,
                batch_size,
                offset,
            )
            if not rows:
                break
            yield [dict(row) for row in rows]
            if len(rows) < batch_size:
                break
            offset += batch_size

    async def stream_cities(self, *, batch_size: int = 500) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield geo city rows for indexing."""
        offset = 0
        while True:
            rows = await fetch(
                """
                SELECT
                    c.id,
                    c.name,
                    s.name AS state_name,
                    co.name AS country_name,
                    co.iso2 AS country_iso2
                FROM geo_cities c
                JOIN geo_states s ON s.id = c.state_id
                JOIN geo_countries co ON co.id = c.country_id
                ORDER BY c.id
                LIMIT $1 OFFSET $2
                """,
                batch_size,
                offset,
            )
            if not rows:
                break
            yield [dict(row) for row in rows]
            if len(rows) < batch_size:
                break
            offset += batch_size

    async def stream_countries(
        self,
        *,
        batch_size: int = 500,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield geo country rows for indexing."""
        offset = 0
        while True:
            rows = await fetch(
                """
                SELECT id, name, iso2
                FROM geo_countries
                ORDER BY id
                LIMIT $1 OFFSET $2
                """,
                batch_size,
                offset,
            )
            if not rows:
                break
            yield [dict(row) for row in rows]
            if len(rows) < batch_size:
                break
            offset += batch_size

    async def stream_states(self, *, batch_size: int = 500) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield geo state rows for indexing."""
        offset = 0
        while True:
            rows = await fetch(
                """
                SELECT
                    s.id,
                    s.name,
                    c.name AS country_name,
                    c.iso2 AS country_iso2
                FROM geo_states s
                JOIN geo_countries c ON c.id = s.country_id
                ORDER BY s.id
                LIMIT $1 OFFSET $2
                """,
                batch_size,
                offset,
            )
            if not rows:
                break
            yield [dict(row) for row in rows]
            if len(rows) < batch_size:
                break
            offset += batch_size

    async def get_user_search_row(self, user_id: str) -> dict[str, Any] | None:
        """Return a single enriched user row for indexing."""
        rows = await fetch(
            """
            SELECT
                u.id,
                u.display_name,
                u.account_mode,
                u.email_verified,
                u.status,
                u.onboarding_completed_at,
                u.created_at,
                u.updated_at,
                ep.avatar_url AS avatar_url,
                COALESCE(ep.visibility, 'discoverable') AS visibility,
                COALESCE(ups.allow_search_discovery, true) AS allow_search_discovery,
                COALESCE(ep.last_active_at, ep.updated_at, cp.updated_at) AS recent_activity_at,
                ep.updated_at AS profile_updated_at,
                gc.name AS home_country_name,
                gs.name AS home_state_name,
                gci.name AS home_city_name,
                COALESCE(ep.custom_home_country_name, cp.custom_home_country_name)
                    AS custom_home_country_name,
                COALESCE(ep.custom_home_state_name, cp.custom_home_state_name)
                    AS custom_home_state_name,
                COALESCE(ep.custom_home_city_name, cp.custom_home_city_name)
                    AS custom_home_city_name,
                (
                    SELECT COUNT(*)::int
                    FROM user_connections c
                    WHERE c.status = 'active'
                      AND (c.user_a_id = u.id OR c.user_b_id = u.id)
                ) AS connections_count,
                0::float AS search_popularity
            FROM users u
            LEFT JOIN explorer_profiles ep ON ep.user_id = u.id
            LEFT JOIN connector_profiles cp ON cp.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            LEFT JOIN geo_countries gc ON gc.id = COALESCE(ep.home_country_id, cp.home_country_id)
            LEFT JOIN geo_states gs ON gs.id = COALESCE(ep.home_state_id, cp.home_state_id)
            LEFT JOIN geo_cities gci ON gci.id = COALESCE(ep.home_city_id, cp.home_city_id)
            WHERE u.id = $1::uuid
            """,
            user_id,
        )
        return dict(rows[0]) if rows else None

    async def get_traveler_search_row(self, user_id: str) -> dict[str, Any] | None:
        """Return a single traveler snapshot row for indexing."""
        rows = await fetch(
            """
            SELECT
                s.*,
                u.email_verified,
                (u.onboarding_completed_at IS NOT NULL) AS profile_completed
            FROM explorer_discovery_snapshots s
            JOIN users u ON u.id = s.user_id
            WHERE s.user_id = $1::uuid
            """,
            user_id,
        )
        return dict(rows[0]) if rows else None
