"""Search analytics recording and suggestions."""

from __future__ import annotations

from typing import Any

from infrastructure.database.repositories.search_analytics import SearchAnalyticsRepository
from infrastructure.redis.search_cache import search_redis_cache


class SearchAnalyticsService:
    """Record and serve search analytics data."""

    def __init__(self, repo: SearchAnalyticsRepository | None = None) -> None:
        self._repo = repo or SearchAnalyticsRepository()

    async def record_event(
        self,
        *,
        user_id: str | None,
        query: str,
        result_type: str,
        result_id: str | None = None,
        clicked: bool = False,
    ) -> dict[str, Any]:
        """Persist a search analytics event."""
        return await self._repo.insert_event(
            user_id=user_id,
            query=query,
            result_type=result_type,
            result_id=result_id,
            clicked=clicked,
        )

    async def recent_searches(self, user_id: str) -> list[str]:
        """Return recent searches for a user from Redis."""
        return await search_redis_cache.get_recent_searches(user_id)

    async def remember_query(self, user_id: str | None, query: str) -> None:
        """Store a query in the user's recent searches list."""
        if user_id:
            await search_redis_cache.push_recent_search(user_id, query)

    async def popular_queries(
        self,
        *,
        result_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return aggregated popular queries from Postgres."""
        rows = await self._repo.list_popular_queries(
            result_type=result_type,
            limit=limit,
        )
        return [
            {"id": row["label"], "label": row["label"], "kind": row["kind"], "score": row["score"]}
            for row in rows
        ]
