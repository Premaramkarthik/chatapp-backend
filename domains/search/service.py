"""Typesense search orchestration with cache-aside."""

from __future__ import annotations

from typing import Any

from core.config.settings import settings
from domains.search.filters import (
    TravelerSearchFilters,
    build_role_filter,
    build_traveler_filters,
    build_viewer_filters,
    combine_filters,
    load_block_exclusions,
)
from infrastructure.redis.search_cache import search_redis_cache
from infrastructure.typesense.client import get_typesense_async_client
from v1.utils.base import TypesenseIntegrationError

USER_SORT = "_text_match:desc,verified:desc,recent_activity_at:desc"
TRAVELER_SORT = "_text_match:desc,has_upcoming_trip:desc,departure_date:asc"


class SearchService:
    """Cache-aside Typesense search service."""

    def __init__(self) -> None:
        self._cache = search_redis_cache

    def _enabled(self) -> bool:
        return settings.typesense.enabled

    async def _search_collection(
        self,
        *,
        collection: str,
        params: dict[str, Any],
        endpoint: str,
        cache_key: str,
    ) -> dict[str, Any]:
        """Run a single-collection search with cache-aside."""
        if not self._enabled():
            return {"hits": [], "found": 0}

        cached = await self._cache.get_json(cache_key)
        if cached is not None:
            return cached

        pass
        try:
            client = get_typesense_async_client()
            raw = await client.collections[collection].documents.search(params)
        except Exception as exc:
            raise TypesenseIntegrationError(str(exc)) from exc

        result = {
            "hits": raw.get("hits") or [],
            "found": int(raw.get("found") or 0),
        }
        await self._cache.set_json(cache_key, result, endpoint=endpoint)
        return result

    async def search_users(
        self,
        *,
        q: str,
        viewer_id: str | None,
        page: int = 1,
        limit: int = 20,
        role: str | None = None,
    ) -> dict[str, Any]:
        """Search users with ranking and visibility filters."""
        blocked = await load_block_exclusions(viewer_id)
        filter_by = combine_filters(
            build_viewer_filters(viewer_id, blocked),
            build_role_filter(role),
        )
        cache_key = self._cache.key_for(
            "user",
            q=q.strip().lower(),
            page=page,
            limit=limit,
            viewer=viewer_id or "",
            filter=filter_by,
            role=role or "",
        )
        params: dict[str, Any] = {
            "q": q or "*",
            "query_by": "username,full_name",
            "filter_by": filter_by,
            "sort_by": USER_SORT,
            "page": page,
            "per_page": limit,
        }
        return await self._search_collection(
            collection=settings.typesense.users_collection,
            params=params,
            endpoint="user",
            cache_key=cache_key,
        )

    async def search_travelers(
        self,
        filters: TravelerSearchFilters,
        *,
        viewer_id: str | None,
    ) -> dict[str, Any]:
        """Search travelers with route and visibility filters."""
        blocked = await load_block_exclusions(viewer_id)
        viewer_filter = build_viewer_filters(viewer_id, blocked)
        traveler_filter = build_traveler_filters(filters)
        filter_by = combine_filters(viewer_filter, traveler_filter)
        page = filters.page if filters.page > 0 else (filters.offset // filters.limit) + 1
        cache_key = self._cache.key_for(
            "traveler",
            q=filters.q.strip().lower(),
            page=page,
            limit=filters.limit,
            viewer=viewer_id or "",
            filter=filter_by,
        )
        params: dict[str, Any] = {
            "q": filters.q or "*",
            "query_by": "from_city,to_city,from_country,to_country",
            "filter_by": filter_by,
            "sort_by": TRAVELER_SORT,
            "page": page,
            "per_page": filters.limit,
        }
        return await self._search_collection(
            collection=settings.typesense.travelers_collection,
            params=params,
            endpoint="traveler",
            cache_key=cache_key,
        )

    async def search_cities(self, *, q: str, limit: int = 20) -> dict[str, Any]:
        """Search cities for autocomplete."""
        cache_key = self._cache.key_for("city", q=q.strip().lower(), limit=limit)
        params = {
            "q": q or "*",
            "query_by": "city_name,state_name,country_name",
            "per_page": limit,
        }
        return await self._search_collection(
            collection=settings.typesense.cities_collection,
            params=params,
            endpoint="city",
            cache_key=cache_key,
        )

    async def search_countries(self, *, q: str, limit: int = 20) -> dict[str, Any]:
        """Search countries for autocomplete."""
        cache_key = self._cache.key_for("country", q=q.strip().lower(), limit=limit)
        params = {
            "q": q or "*",
            "query_by": "country_name,iso2",
            "per_page": limit,
        }
        return await self._search_collection(
            collection=settings.typesense.countries_collection,
            params=params,
            endpoint="country",
            cache_key=cache_key,
        )

    async def search_states(
        self,
        *,
        q: str,
        country_iso2: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search states for autocomplete."""
        cache_key = self._cache.key_for(
            "state",
            q=q.strip().lower(),
            country=country_iso2 or "",
            limit=limit,
        )
        params: dict[str, Any] = {
            "q": q or "*",
            "query_by": "state_name,country_name",
            "per_page": limit,
        }
        if country_iso2:
            params["filter_by"] = f"country_iso2:={country_iso2.upper()}"
        return await self._search_collection(
            collection=settings.typesense.states_collection,
            params=params,
            endpoint="state",
            cache_key=cache_key,
        )

    async def global_search(
        self,
        *,
        q: str,
        viewer_id: str | None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Run grouped multi-search across core collections."""
        if not self._enabled():
            return {
                "users": [],
                "travelers": [],
                "cities": [],
                "countries": [],
                "states": [],
                "requests": [],
            }

        blocked = await load_block_exclusions(viewer_id)
        viewer_filter = build_viewer_filters(viewer_id, blocked)
        cache_key = self._cache.key_for(
            "global",
            q=q.strip().lower(),
            limit=limit,
            viewer=viewer_id or "",
        )
        cached = await self._cache.get_json(cache_key)
        if cached is not None:
            return cached

        searches = [
            {
                "collection": settings.typesense.users_collection,
                "q": q or "*",
                "query_by": "username,full_name",
                "filter_by": viewer_filter,
                "sort_by": USER_SORT,
                "per_page": limit,
            },
            {
                "collection": settings.typesense.travelers_collection,
                "q": q or "*",
                "query_by": "from_city,to_city,from_country,to_country",
                "filter_by": viewer_filter,
                "sort_by": TRAVELER_SORT,
                "per_page": limit,
            },
            {
                "collection": settings.typesense.cities_collection,
                "q": q or "*",
                "query_by": "city_name,state_name,country_name",
                "per_page": limit,
            },
            {
                "collection": settings.typesense.countries_collection,
                "q": q or "*",
                "query_by": "country_name,iso2",
                "per_page": limit,
            },
            {
                "collection": settings.typesense.states_collection,
                "q": q or "*",
                "query_by": "state_name,country_name",
                "per_page": limit,
            },
        ]
        pass
        try:
            client = get_typesense_async_client()
            raw = await client.multi_search.perform({"searches": searches}, {})
        except Exception as exc:
            raise TypesenseIntegrationError(str(exc)) from exc

        results = raw.get("results") or []

        def _docs(index: int) -> list[dict[str, Any]]:
            if index >= len(results):
                return []
            return [hit.get("document") or {} for hit in results[index].get("hits") or []]

        payload = {
            "users": _docs(0),
            "travelers": _docs(1),
            "cities": _docs(2),
            "countries": _docs(3),
            "states": _docs(4),
            "requests": [],
        }
        await self._cache.set_json(cache_key, payload, endpoint="global")
        return payload

    async def search_popular_searches(self, *, limit: int = 10) -> dict[str, Any]:
        """Search the popular_searches collection."""
        cache_key = self._cache.key_for("popular", limit=limit)
        params = {
            "q": "*",
            "query_by": "label",
            "sort_by": "score:desc",
            "per_page": limit,
        }
        return await self._search_collection(
            collection=settings.typesense.popular_searches_collection,
            params=params,
            endpoint="popular",
            cache_key=cache_key,
        )

    async def search_route_suggestions(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return top traveler route pairs as suggestion labels."""
        if not self._enabled():
            return []
        params = {
            "q": "*",
            "query_by": "from_country,to_country",
            "filter_by": "is_searchable:=true",
            "per_page": 50,
        }
        try:
            client = get_typesense_async_client()
            result = await client.collections[
                settings.typesense.travelers_collection
            ].documents.search(params)
        except Exception:
            return []
        counts: dict[str, int] = {}
        for hit in result.get("hits") or []:
            doc = hit.get("document") or {}
            from_country = doc.get("from_country") or ""
            to_country = doc.get("to_country") or ""
            if not from_country or not to_country:
                continue
            label = f"{from_country} → {to_country}"
            counts[label] = counts.get(label, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
        return [
            {"id": label, "label": label, "kind": "route", "score": float(score)}
            for label, score in ranked
        ]
