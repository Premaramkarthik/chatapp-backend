"""Enriched connection hub queries for screen-oriented APIs."""

from __future__ import annotations

from typing import Any

from domains.chat.permissions import conversation_permissions
from infrastructure.database.connection import fetch
from infrastructure.database.repositories.matching import PostgresMatchingRepository

_PEER_SELECT = """
SELECT
    u.id::text AS user_id,
    u.display_name,
    u.account_mode,
    ep.avatar_url,
    ep.headline,
    NULLIF(
        TRIM(
            CONCAT_WS(
                ', ',
                COALESCE(
                    ep.custom_home_city_name,
                    gci_ep.name,
                    cp.custom_home_city_name,
                    gci_cp.name
                ),
                COALESCE(gc_ep.iso2, gc_cp.iso2)
            )
        ),
        ''
    ) AS home_label,
    COALESCE(gc_dest.iso2, gc_ep.iso2, gc_cp.iso2) AS destination_country_iso,
    COALESCE(tdest.custom_city_name, gci_dest.name) AS destination_city_name,
    COALESCE(ep.languages, '{}'::text[]) AS languages,
    COALESCE(ep.last_active_at, ep.updated_at, cp.updated_at) AS last_active_at
FROM users u
LEFT JOIN explorer_profiles ep ON ep.user_id = u.id
LEFT JOIN connector_profiles cp ON cp.user_id = u.id
LEFT JOIN geo_countries gc_ep ON gc_ep.id = ep.home_country_id
LEFT JOIN geo_cities gci_ep ON gci_ep.id = ep.home_city_id
LEFT JOIN geo_countries gc_cp ON gc_cp.id = cp.home_country_id
LEFT JOIN geo_cities gci_cp ON gci_cp.id = cp.home_city_id
LEFT JOIN LATERAL (
    SELECT tp.id
    FROM travel_plans tp
    WHERE tp.user_id = u.id AND tp.status = 'active'
    ORDER BY tp.is_primary DESC, tp.updated_at DESC
    LIMIT 1
) tplan ON true
LEFT JOIN LATERAL (
    SELECT country_id, city_id, custom_city_name
    FROM travel_plan_destinations
    WHERE travel_plan_id = tplan.id
    ORDER BY sort_order ASC
    LIMIT 1
) tdest ON true
LEFT JOIN geo_countries gc_dest ON gc_dest.id = tdest.country_id
LEFT JOIN geo_cities gci_dest ON gci_dest.id = tdest.city_id
WHERE u.id = ANY($1::uuid[])
"""


def _peer_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a peer enrichment row for API schemas."""
    languages = row.get("languages") or []
    if not isinstance(languages, list):
        languages = list(languages)
    return {
        "user_id": row["user_id"],
        "display_name": row.get("display_name"),
        "account_mode": row.get("account_mode"),
        "avatar_url": row.get("avatar_url"),
        "headline": row.get("headline"),
        "home_label": row.get("home_label"),
        "destination_country_iso": row.get("destination_country_iso"),
        "destination_city_name": row.get("destination_city_name"),
        "languages": languages,
        "last_active_at": row.get("last_active_at"),
    }


def _empty_peer(user_id: str) -> dict[str, Any]:
    """Fallback peer when enrichment row is missing."""
    return {
        "user_id": user_id,
        "display_name": None,
        "account_mode": None,
        "avatar_url": None,
        "headline": None,
        "home_label": None,
        "destination_country_iso": None,
        "destination_city_name": None,
        "languages": [],
        "last_active_at": None,
    }


class ConnectionScreenRepository:
    """Postgres access for connections hub screens."""

    def __init__(self, matching: PostgresMatchingRepository | None = None) -> None:
        self._matching = matching or PostgresMatchingRepository()

    async def fetch_peers(self, user_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return peer summaries keyed by user id."""
        if not user_ids:
            return {}
        unique_ids = list(dict.fromkeys(user_ids))
        rows = await fetch(_PEER_SELECT, unique_ids)
        by_id = {str(dict(row)["user_id"]): _peer_from_row(dict(row)) for row in rows}
        return {uid: by_id.get(uid, _empty_peer(uid)) for uid in unique_ids}

    async def summary(self, viewer_id: str) -> dict[str, int]:
        """Return tab counts for the connections hub."""
        rows = await fetch(
            """
            SELECT
                (
                    SELECT COUNT(*)::int
                    FROM connection_requests cr
                    WHERE cr.recipient_id = $1::uuid AND cr.status = 'pending'
                ) AS incoming_pending,
                (
                    SELECT COUNT(*)::int
                    FROM connection_requests cr
                    WHERE cr.requester_id = $1::uuid AND cr.status = 'pending'
                ) AS sent_pending,
                (
                    SELECT COUNT(*)::int
                    FROM user_connections uc
                    WHERE uc.status = 'active'
                      AND ($1::uuid = uc.user_a_id OR $1::uuid = uc.user_b_id)
                ) AS active,
                (
                    SELECT COUNT(*)::int FROM (
                        SELECT cr.id
                        FROM connection_requests cr
                        WHERE (cr.requester_id = $1::uuid OR cr.recipient_id = $1::uuid)
                          AND cr.status IN ('rejected', 'cancelled', 'expired')
                        UNION ALL
                        SELECT uc.id
                        FROM user_connections uc
                        WHERE uc.status = 'removed'
                          AND ($1::uuid = uc.user_a_id OR $1::uuid = uc.user_b_id)
                    ) history_rows
                ) AS history_count
            """,
            viewer_id,
        )
        row = dict(rows[0])
        return {
            "incoming_pending": int(row["incoming_pending"]),
            "sent_pending": int(row["sent_pending"]),
            "active": int(row["active"]),
            "history_count": int(row["history_count"]),
        }

    async def list_incoming(self, viewer_id: str) -> list[dict[str, Any]]:
        """List pending incoming requests with peer enrichment."""
        raw_rows = await self._matching.list_incoming_requests(viewer_id)
        peer_ids = [str(row["requester_id"]) for row in raw_rows]
        peers = await self.fetch_peers(peer_ids)
        return [
            {
                "request_id": row["id"],
                "message": row.get("message"),
                "status": row["status"],
                "created_at": row["created_at"],
                "expires_at": row.get("expires_at"),
                "peer": peers[str(row["requester_id"])],
            }
            for row in raw_rows
        ]

    async def list_sent(self, viewer_id: str) -> list[dict[str, Any]]:
        """List pending outgoing requests with peer enrichment."""
        raw_rows = await self._matching.list_outgoing_requests(viewer_id)
        peer_ids = [str(row["recipient_id"]) for row in raw_rows]
        peers = await self.fetch_peers(peer_ids)
        return [
            {
                "request_id": row["id"],
                "message": row.get("message"),
                "status": row["status"],
                "created_at": row["created_at"],
                "expires_at": row.get("expires_at"),
                "peer": peers[str(row["recipient_id"])],
            }
            for row in raw_rows
        ]

    async def list_active(self, viewer_id: str) -> list[dict[str, Any]]:
        """List active connections with peer enrichment and chat hints."""
        raw_rows = await self._matching.list_connections(viewer_id)
        if not raw_rows:
            return []
        connection_ids = [str(row["id"]) for row in raw_rows]
        peer_ids = [
            str(row["user_b_id"]) if str(row["user_a_id"]) == viewer_id else str(row["user_a_id"])
            for row in raw_rows
        ]
        peers = await self.fetch_peers(peer_ids)
        mapping_rows = await fetch(
            """
            SELECT
                m.user_connection_id::text AS connection_id,
                m.status AS conversation_status,
                (
                    m.status = 'active'
                    AND m.room_id LIKE '!%'
                    AND m.room_id NOT LIKE '!pending_%'
                ) AS can_chat,
                EXISTS (
                    SELECT 1 FROM matrix_inbox_archive ia
                    WHERE ia.user_id = $2::uuid
                      AND ia.user_connection_id = m.user_connection_id
                ) AS is_user_archived
            FROM matrix_room_mappings m
            WHERE m.user_connection_id = ANY($1::uuid[])
            """,
            connection_ids,
            viewer_id,
        )
        mapping_by_conn = {str(row["connection_id"]): dict(row) for row in mapping_rows}
        items: list[dict[str, Any]] = []
        for row, peer_id in zip(raw_rows, peer_ids, strict=True):
            conn_id = str(row["id"])
            mapping = mapping_by_conn.get(conn_id, {})
            conv_status = mapping.get("conversation_status")
            perms = conversation_permissions(
                mapping_status=conv_status,
                can_chat=bool(mapping.get("can_chat")),
                has_mapping=bool(conv_status),
                is_user_archived=bool(mapping.get("is_user_archived")),
            )
            items.append(
                {
                    "connection_id": row["id"],
                    "connected_at": row["connected_at"],
                    "peer": peers[peer_id],
                    "can_chat": perms["can_chat"],
                    "conversation_status": conv_status,
                    "is_archived": perms["is_archived"],
                    "can_archive": perms["can_archive"],
                    "can_reopen": perms["can_reopen"],
                }
            )
        return items

    async def list_history(self, viewer_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """List terminal requests and removed connections."""
        capped = max(1, min(limit, 100))
        rows = await fetch(
            """
            SELECT kind, occurred_at, message, request_id, connection_id, peer_user_id
            FROM (
                SELECT
                    CASE cr.status
                        WHEN 'rejected' THEN 'request_rejected'
                        WHEN 'cancelled' THEN 'request_cancelled'
                        WHEN 'expired' THEN 'request_expired'
                    END AS kind,
                    COALESCE(cr.responded_at, cr.updated_at, cr.created_at) AS occurred_at,
                    cr.message,
                    cr.id AS request_id,
                    NULL::uuid AS connection_id,
                    CASE
                        WHEN cr.requester_id = $1::uuid THEN cr.recipient_id
                        ELSE cr.requester_id
                    END AS peer_user_id
                FROM connection_requests cr
                WHERE (cr.requester_id = $1::uuid OR cr.recipient_id = $1::uuid)
                  AND cr.status IN ('rejected', 'cancelled', 'expired')

                UNION ALL

                SELECT
                    'connection_removed'::text AS kind,
                    COALESCE(uc.connected_at, uc.created_at) AS occurred_at,
                    NULL::text AS message,
                    NULL::uuid AS request_id,
                    uc.id AS connection_id,
                    CASE
                        WHEN uc.user_a_id = $1::uuid THEN uc.user_b_id
                        ELSE uc.user_a_id
                    END AS peer_user_id
                FROM user_connections uc
                WHERE uc.status = 'removed'
                  AND ($1::uuid = uc.user_a_id OR $1::uuid = uc.user_b_id)
            ) history
            ORDER BY occurred_at DESC
            LIMIT $2
            """,
            viewer_id,
            capped,
        )
        peer_ids = [str(row["peer_user_id"]) for row in rows]
        peers = await self.fetch_peers(peer_ids)
        return [
            {
                "kind": row["kind"],
                "occurred_at": row["occurred_at"],
                "message": row.get("message"),
                "request_id": row.get("request_id"),
                "connection_id": row.get("connection_id"),
                "peer": peers[str(row["peer_user_id"])],
            }
            for row in rows
        ]
