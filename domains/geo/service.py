"""Geo autocomplete service with Redis cache-aside."""

from __future__ import annotations

from typing import Any

from core.config.settings import settings
from infrastructure.database.repositories.geo import PostgresGeoRepository
from infrastructure.redis.cache import GeoRedisCache, geo_redis_cache


class GeoService:
    """Read-only geo autocomplete backed by Postgres and Redis."""

    def __init__(
        self,
        repository: PostgresGeoRepository | None = None,
        cache: GeoRedisCache | None = None,
    ) -> None:
        self._repo = repository or PostgresGeoRepository()
        self._cache = cache or geo_redis_cache

    def _clamp_search_limit(self, limit: int | None) -> int:
        """Cap limits for non-empty search queries."""
        default = settings.geo.search_default_limit
        maximum = settings.geo.search_max_limit
        value = default if limit is None else limit
        return max(1, min(value, maximum))

    def _clamp_list_limit(self, limit: int | None, *, list_cap: int) -> int:
        """Cap limits for empty-search list loads (client-side filter)."""
        value = list_cap if limit is None else limit
        return max(1, min(value, list_cap))

    def _effective_limit(self, search: str, limit: int | None, *, list_cap: int) -> int:
        """Use list cap when search is empty; otherwise use search cap."""
        if not search.strip():
            return self._clamp_list_limit(limit, list_cap=list_cap)
        return self._clamp_search_limit(limit)

    async def search_countries(
        self, search: str = "", *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return countries for autocomplete."""
        capped = self._effective_limit(
            search,
            limit,
            list_cap=settings.geo.list_limit_countries,
        )
        key = GeoRedisCache.search_key("countries", limit=capped, search=search)
        cached = await self._cache.get_json(key, resource="countries")
        if cached is not None:
            return cached
        rows = await self._repo.search_countries(search, limit=capped)
        await self._cache.set_json(
            key,
            rows,
            resource="countries",
            ttl_sec=settings.geo.cache_ttl_countries_sec,
        )
        return rows

    async def search_states(
        self,
        country_id: int,
        search: str = "",
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return states for a country."""
        capped = self._effective_limit(
            search,
            limit,
            list_cap=settings.geo.list_limit_states,
        )
        key = GeoRedisCache.search_key(
            "states",
            limit=capped,
            search=search,
            parent_id=country_id,
        )
        cached = await self._cache.get_json(key, resource="states")
        if cached is not None:
            return cached
        rows = await self._repo.search_states(country_id, search, limit=capped)
        await self._cache.set_json(
            key,
            rows,
            resource="states",
            ttl_sec=settings.geo.cache_ttl_states_sec,
        )
        return rows

    async def search_cities(
        self,
        state_id: int,
        search: str = "",
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return cities for a state."""
        capped = self._effective_limit(
            search,
            limit,
            list_cap=settings.geo.list_limit_cities,
        )
        key = GeoRedisCache.search_key(
            "cities",
            limit=capped,
            search=search,
            parent_id=state_id,
        )
        cached = await self._cache.get_json(key, resource="cities")
        if cached is not None:
            return cached
        rows = await self._repo.search_cities(state_id, search, limit=capped)
        await self._cache.set_json(
            key,
            rows,
            resource="cities",
            ttl_sec=settings.geo.cache_ttl_cities_sec,
        )
        return rows
