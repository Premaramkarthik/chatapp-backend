"""Search analytics persistence."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import fetch, fetchrow


class SearchAnalyticsRepository:
    """Postgres access for search_events analytics."""

    async def insert_event(
        self,
        *,
        user_id: str | None,
        query: str,
        result_type: str,
        result_id: str | None = None,
        clicked: bool = False,
    ) -> dict[str, Any]:
        """Insert a search analytics event."""
        row = await fetchrow(
            """
            INSERT INTO search_events (user_id, query, result_type, result_id, clicked)
            VALUES ($1::uuid, $2, $3, $4, $5)
            RETURNING id::text, user_id::text, query, result_type, result_id, clicked, created_at
            """,
            user_id,
            query.strip().lower(),
            result_type,
            result_id,
            clicked,
        )
        if row is None:
            raise RuntimeError("search_events insert returned no row")
        return dict(row)

    async def list_popular_queries(
        self,
        *,
        result_type: str | None = None,
        limit: int = 20,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Aggregate popular queries over a rolling window."""
        if result_type:
            rows = await fetch(
                """
                SELECT query AS label, COUNT(*)::float AS score, 'query' AS kind
                FROM search_events
                WHERE created_at >= now() - ($2::int || ' days')::interval
                  AND result_type = $3
                  AND query <> ''
                GROUP BY query
                ORDER BY score DESC
                LIMIT $1
                """,
                limit,
                days,
                result_type,
            )
        else:
            rows = await fetch(
                """
                SELECT query AS label, COUNT(*)::float AS score, 'query' AS kind
                FROM search_events
                WHERE created_at >= now() - ($2::int || ' days')::interval
                  AND query <> ''
                GROUP BY query
                ORDER BY score DESC
                LIMIT $1
                """,
                limit,
                days,
            )
        return [dict(row) for row in rows]
