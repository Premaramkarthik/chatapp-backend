"""Recommendation search stub (Phase 1)."""

from __future__ import annotations

from typing import Any


class RecommendationService:
    """Stub recommendation service until scoring ships."""

    async def suggested_people(self, user_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return suggested people for a user (stub)."""
        _ = user_id, limit
        return []
