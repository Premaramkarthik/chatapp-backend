"""Discovery snapshots and search outbox."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function, fetch
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb

_NAME_SLUG_MATCH = (
    "LOWER(REGEXP_REPLACE(COALESCE(s.display_name, u.display_name, ''), "
    "'[^a-zA-Z0-9]+', '', 'g'))\n"
    "                     LIKE '%' || LOWER(REGEXP_REPLACE({param}, "
    "'[^a-zA-Z0-9]+', '', 'g')) || '%'"
)


def _name_slug_match(param: str) -> str:
    """SQL fragment matching display-name slug against a bind parameter."""
    return _NAME_SLUG_MATCH.format(param=param)


class PostgresDiscoveryRepository:
    """Postgres access for explorer_discovery_snapshots and search outbox."""

    async def get_snapshot(self, user_id: str) -> dict[str, Any] | None:
        """Return a snapshot row by user id."""
        result = await call_json_function(
            "fn_discovery_snapshots",
            2,
            {"user_id": user_id},
        )
        return row_from_jsonb(result)

    async def rebuild_snapshot(self, user_id: str) -> dict[str, Any] | None:
        """Rebuild denormalized discovery row from profile, trip, and privacy data."""
        result = await call_json_function(
            "fn_discovery_snapshots",
            1,
            {"user_id": user_id},
        )
        return row_from_jsonb(result)

    async def list_postgres_search(
        self,
        *,
        destination_country: str,
        current_country: str | None,
        viewer_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Fallback search on snapshots with block exclusion."""
        payload: dict[str, Any] = {
            "destination_country": destination_country,
            "viewer_id": viewer_id,
            "limit": limit,
            "offset": offset,
        }
        if current_country:
            payload["current_country"] = current_country
        result = await call_json_function("fn_discovery_snapshots", 3, payload)
        return list_from_jsonb(result)

    async def list_discoverable_explorers(
        self,
        *,
        destination_country: str,
        q: str = "",
        current_country: str | None = None,
        viewer_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return discoverable explorer cards matching destination and optional keyword."""
        country = destination_country.strip().upper()
        keyword = q.strip()
        cur_country = current_country.strip().upper() if current_country else None
        count_row = await fetch(
            f"""
            SELECT COUNT(*)::int AS total
            FROM users u
            INNER JOIN explorer_discovery_snapshots s ON s.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            WHERE u.account_mode = 'explorer'
              AND u.status = 'active'
              AND s.is_discoverable = true
              AND COALESCE(ups.allow_search_discovery, true)
              AND u.id <> $1::uuid
              AND s.destination_country_iso = $2::char(2)
              AND ($3::char(2) IS NULL OR s.current_country_iso = $3::char(2))
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks b
                  WHERE (b.blocker_id = $1::uuid AND b.blocked_id = u.id)
                     OR (b.blocker_id = u.id AND b.blocked_id = $1::uuid)
              )
              AND (
                  $4::text = ''
                  OR COALESCE(s.display_name, u.display_name, '') ILIKE '%' || $4 || '%'
                  OR COALESCE(s.headline, '') ILIKE '%' || $4 || '%'
                  OR {_name_slug_match("$4")}
              )
            """,
            viewer_id,
            country,
            cur_country,
            keyword,
        )
        total = int(count_row[0]["total"]) if count_row else 0
        rows = await fetch(
            f"""
            SELECT
                u.id::text AS user_id,
                COALESCE(s.display_name, u.display_name) AS display_name,
                s.headline,
                s.avatar_url,
                s.destination_country_iso,
                s.destination_city_name,
                s.current_country_iso,
                s.languages,
                s.interests,
                s.connection_availability,
                s.last_active_at
            FROM users u
            INNER JOIN explorer_discovery_snapshots s ON s.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            WHERE u.account_mode = 'explorer'
              AND u.status = 'active'
              AND s.is_discoverable = true
              AND COALESCE(ups.allow_search_discovery, true)
              AND u.id <> $1::uuid
              AND s.destination_country_iso = $2::char(2)
              AND ($3::char(2) IS NULL OR s.current_country_iso = $3::char(2))
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks b
                  WHERE (b.blocker_id = $1::uuid AND b.blocked_id = u.id)
                     OR (b.blocker_id = u.id AND b.blocked_id = $1::uuid)
              )
              AND (
                  $4::text = ''
                  OR COALESCE(s.display_name, u.display_name, '') ILIKE '%' || $4 || '%'
                  OR COALESCE(s.headline, '') ILIKE '%' || $4 || '%'
                  OR {_name_slug_match("$4")}
              )
            ORDER BY s.last_active_at DESC NULLS LAST, s.display_name ASC NULLS LAST
            LIMIT $5 OFFSET $6
            """,
            viewer_id,
            country,
            cur_country,
            keyword,
            limit,
            offset,
        )
        return [dict(row) for row in rows], total

    async def fetch_public_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        """Return discoverable snapshot rows for a set of user ids."""
        if not user_ids:
            return []
        result = await call_json_function(
            "fn_discovery_snapshots",
            4,
            {"user_ids": user_ids},
        )
        return list_from_jsonb(result)

    async def search_by_username(
        self,
        *,
        q: str,
        viewer_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search discoverable explorers by display name, email, or username slug."""
        keyword = q.strip()
        count_row = await fetch(
            f"""
            SELECT COUNT(*)::int AS total
            FROM users u
            INNER JOIN explorer_discovery_snapshots s ON s.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            WHERE u.account_mode = 'explorer'
              AND u.status = 'active'
              AND s.is_discoverable = true
              AND COALESCE(ups.allow_search_discovery, true)
              AND u.id <> $1::uuid
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks b
                  WHERE (b.blocker_id = $1::uuid AND b.blocked_id = u.id)
                     OR (b.blocker_id = u.id AND b.blocked_id = $1::uuid)
              )
              AND (
                  COALESCE(s.display_name, u.display_name, '') ILIKE '%' || $2 || '%'
                  OR u.email ILIKE '%' || $2 || '%'
                  OR COALESCE(s.headline, '') ILIKE '%' || $2 || '%'
                  OR {_name_slug_match("$2")}
              )
            """,
            viewer_id,
            keyword,
        )
        total = int(count_row[0]["total"]) if count_row else 0
        rows = await fetch(
            f"""
            SELECT
                u.id::text AS user_id,
                COALESCE(s.display_name, u.display_name) AS display_name,
                u.email,
                s.headline,
                s.avatar_url,
                s.destination_country_iso,
                s.connection_availability,
                s.home_country_iso
            FROM users u
            INNER JOIN explorer_discovery_snapshots s ON s.user_id = u.id
            LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
            WHERE u.account_mode = 'explorer'
              AND u.status = 'active'
              AND s.is_discoverable = true
              AND COALESCE(ups.allow_search_discovery, true)
              AND u.id <> $1::uuid
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks b
                  WHERE (b.blocker_id = $1::uuid AND b.blocked_id = u.id)
                     OR (b.blocker_id = u.id AND b.blocked_id = $1::uuid)
              )
              AND (
                  COALESCE(s.display_name, u.display_name, '') ILIKE '%' || $2 || '%'
                  OR u.email ILIKE '%' || $2 || '%'
                  OR COALESCE(s.headline, '') ILIKE '%' || $2 || '%'
                  OR {_name_slug_match("$2")}
              )
            ORDER BY s.last_active_at DESC NULLS LAST, s.display_name ASC NULLS LAST
            LIMIT $3 OFFSET $4
            """,
            viewer_id,
            keyword,
            limit,
            offset,
        )
        return [dict(row) for row in rows], total

    async def claim_outbox_batch(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Claim pending outbox rows for processing."""
        result = await call_json_function(
            "fn_search_outbox_events",
            1,
            {"limit": limit},
        )
        return list_from_jsonb(result)

    async def complete_outbox(self, event_id: str) -> None:
        """Mark an outbox event completed."""
        await call_json_function(
            "fn_search_outbox_events",
            2,
            {"event_id": event_id},
        )

    async def fail_outbox(self, event_id: str, error: str) -> None:
        """Mark an outbox event failed and reschedule with backoff."""
        await call_json_function(
            "fn_search_outbox_events",
            3,
            {"event_id": event_id, "error": error},
        )
