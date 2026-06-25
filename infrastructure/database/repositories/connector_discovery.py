"""Connector discovery queries for explorer search."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import fetch


class PostgresConnectorDiscoveryRepository:
    """Postgres access for discoverable connector search."""

    async def list_discoverable_connectors(
        self,
        *,
        destination_country: str,
        q: str = "",
        viewer_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return connector cards matching destination and optional keyword."""
        country = destination_country.strip().upper()
        keyword = q.strip()
        count_row = await fetch(
            """
            SELECT COUNT(*)::int AS total
            FROM users u
            INNER JOIN connector_profiles cp ON cp.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            LEFT JOIN geo_countries gc ON gc.id = cp.home_country_id
            LEFT JOIN geo_cities gci ON gci.id = cp.home_city_id
            WHERE u.account_mode = 'connector'
              AND u.status = 'active'
              AND COALESCE(ups.allow_search_discovery, true)
              AND u.id <> $1::uuid
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks b
                  WHERE (b.blocker_id = $1::uuid AND b.blocked_id = u.id)
                     OR (b.blocker_id = u.id AND b.blocked_id = $1::uuid)
              )
              AND (
                  $2::char(2) = ANY(cp.preferred_destination_countries)
                  OR EXISTS (
                      SELECT 1 FROM geo_countries home_gc
                      WHERE home_gc.id = cp.home_country_id
                        AND home_gc.iso2 = $2::char(2)
                  )
                  OR UPPER(COALESCE(cp.custom_home_country_name, '')) = $2::text
              )
              AND (
                  $3::text = ''
                  OR u.display_name ILIKE '%' || $3 || '%'
                  OR COALESCE(cp.bio, '') ILIKE '%' || $3 || '%'
              )
            """,
            viewer_id,
            country,
            keyword,
        )
        total = int(count_row[0]["total"]) if count_row else 0
        rows = await fetch(
            """
            SELECT
                u.id::text AS user_id,
                u.display_name,
                cp.bio,
                NULL::text AS avatar_url,
                COALESCE(gc.name, cp.custom_home_country_name) AS home_country_label,
                COALESCE(gci.name, cp.custom_home_city_name) AS home_city_label,
                cp.preferred_destination_countries,
                cp.updated_at AS last_active_at
            FROM users u
            INNER JOIN connector_profiles cp ON cp.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            LEFT JOIN geo_countries gc ON gc.id = cp.home_country_id
            LEFT JOIN geo_cities gci ON gci.id = cp.home_city_id
            WHERE u.account_mode = 'connector'
              AND u.status = 'active'
              AND COALESCE(ups.allow_search_discovery, true)
              AND u.id <> $1::uuid
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks b
                  WHERE (b.blocker_id = $1::uuid AND b.blocked_id = u.id)
                     OR (b.blocker_id = u.id AND b.blocked_id = $1::uuid)
              )
              AND (
                  $2::char(2) = ANY(cp.preferred_destination_countries)
                  OR EXISTS (
                      SELECT 1 FROM geo_countries home_gc
                      WHERE home_gc.id = cp.home_country_id
                        AND home_gc.iso2 = $2::char(2)
                  )
                  OR UPPER(COALESCE(cp.custom_home_country_name, '')) = $2::text
              )
              AND (
                  $3::text = ''
                  OR u.display_name ILIKE '%' || $3 || '%'
                  OR COALESCE(cp.bio, '') ILIKE '%' || $3 || '%'
              )
            ORDER BY cp.updated_at DESC NULLS LAST, u.display_name ASC NULLS LAST
            LIMIT $4 OFFSET $5
            """,
            viewer_id,
            country,
            keyword,
            limit,
            offset,
        )
        return [dict(row) for row in rows], total

    async def fetch_public_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        """Return discoverable connector rows for a set of user ids."""
        if not user_ids:
            return []
        rows = await fetch(
            """
            SELECT
                u.id::text AS user_id,
                u.display_name,
                cp.bio,
                NULL::text AS avatar_url,
                COALESCE(gc.name, cp.custom_home_country_name) AS home_country_label,
                COALESCE(gci.name, cp.custom_home_city_name) AS home_city_label,
                cp.preferred_destination_countries,
                cp.updated_at AS last_active_at
            FROM users u
            INNER JOIN connector_profiles cp ON cp.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            LEFT JOIN geo_countries gc ON gc.id = cp.home_country_id
            LEFT JOIN geo_cities gci ON gci.id = cp.home_city_id
            WHERE u.id = ANY($1::uuid[])
              AND u.account_mode = 'connector'
              AND u.status = 'active'
              AND COALESCE(ups.allow_search_discovery, true)
            """,
            user_ids,
        )
        return [dict(row) for row in rows]

    async def search_by_username(
        self,
        *,
        q: str,
        viewer_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search discoverable connectors by display name, email, or username slug."""
        keyword = q.strip()
        count_row = await fetch(
            """
            SELECT COUNT(*)::int AS total
            FROM users u
            INNER JOIN connector_profiles cp ON cp.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            WHERE u.account_mode = 'connector'
              AND u.status = 'active'
              AND COALESCE(ups.allow_search_discovery, true)
              AND u.id <> $1::uuid
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks b
                  WHERE (b.blocker_id = $1::uuid AND b.blocked_id = u.id)
                     OR (b.blocker_id = u.id AND b.blocked_id = $1::uuid)
              )
              AND (
                  u.display_name ILIKE '%' || $2 || '%'
                  OR u.email ILIKE '%' || $2 || '%'
                  OR COALESCE(cp.bio, '') ILIKE '%' || $2 || '%'
                  OR LOWER(REGEXP_REPLACE(COALESCE(u.display_name, ''), '[^a-zA-Z0-9]+', '', 'g'))
                     LIKE '%' || LOWER(REGEXP_REPLACE($2, '[^a-zA-Z0-9]+', '', 'g')) || '%'
              )
            """,
            viewer_id,
            keyword,
        )
        total = int(count_row[0]["total"]) if count_row else 0
        rows = await fetch(
            """
            SELECT
                u.id::text AS user_id,
                u.display_name,
                u.email,
                cp.bio,
                NULL::text AS avatar_url,
                COALESCE(gc.name, cp.custom_home_country_name) AS home_country_label,
                COALESCE(gci.name, cp.custom_home_city_name) AS home_city_label,
                cp.preferred_destination_countries
            FROM users u
            INNER JOIN connector_profiles cp ON cp.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            LEFT JOIN geo_countries gc ON gc.id = cp.home_country_id
            LEFT JOIN geo_cities gci ON gci.id = cp.home_city_id
            WHERE u.account_mode = 'connector'
              AND u.status = 'active'
              AND COALESCE(ups.allow_search_discovery, true)
              AND u.id <> $1::uuid
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks b
                  WHERE (b.blocker_id = $1::uuid AND b.blocked_id = u.id)
                     OR (b.blocker_id = u.id AND b.blocked_id = $1::uuid)
              )
              AND (
                  u.display_name ILIKE '%' || $2 || '%'
                  OR u.email ILIKE '%' || $2 || '%'
                  OR COALESCE(cp.bio, '') ILIKE '%' || $2 || '%'
                  OR LOWER(REGEXP_REPLACE(COALESCE(u.display_name, ''), '[^a-zA-Z0-9]+', '', 'g'))
                     LIKE '%' || LOWER(REGEXP_REPLACE($2, '[^a-zA-Z0-9]+', '', 'g')) || '%'
              )
            ORDER BY u.display_name ASC NULLS LAST, cp.updated_at DESC NULLS LAST
            LIMIT $3 OFFSET $4
            """,
            viewer_id,
            keyword,
            limit,
            offset,
        )
        return [dict(row) for row in rows], total
