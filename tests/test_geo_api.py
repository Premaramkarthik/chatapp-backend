"""Geo autocomplete API tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infrastructure.redis.cache import GeoRedisCache, geo_redis_cache
from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_search_countries_empty_bootstrap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_search(self, search: str = "", *, limit: int | None = None):
        return [{"id": 1, "iso2": "IN", "iso3": "IND", "name": "India", "phone_code": "91"}]

    from domains.geo.service import GeoService

    monkeypatch.setattr(GeoService, "search_countries", fake_search)
    response = client.get("/v1/geo/countries?search=ind")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["iso2"] == "IN"


def test_geo_cache_key_stable() -> None:
    key_a = GeoRedisCache.search_key("countries", limit=20, search="ind")
    key_b = GeoRedisCache.search_key("countries", limit=20, search="ind")
    assert key_a == key_b
    assert key_a.startswith("geo:countries:search:")


@pytest.mark.asyncio
async def test_geo_cache_logs_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    key = GeoRedisCache.search_key("countries", limit=5, search="")
    payload = [{"id": 1, "iso2": "US", "iso3": "USA", "name": "United States", "phone_code": "1"}]
    logs: list[tuple[str, dict]] = []

    def capture_info(_logger, message: str, **context):
        logs.append((message, context))

    monkeypatch.setattr("infrastructure.redis.cache.log_info", capture_info)
    await geo_redis_cache.set_json(key, payload, resource="countries", ttl_sec=60)

    cached = await geo_redis_cache.get_json(key, resource="countries")
    assert cached == payload
    assert any(msg == "Geo cache hit" for msg, _ in logs)


@pytest.mark.asyncio
async def test_geo_cache_logs_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    logs: list[tuple[str, dict]] = []

    def capture_info(_logger, message: str, **context):
        logs.append((message, context))

    monkeypatch.setattr("infrastructure.redis.cache.log_info", capture_info)
    key = GeoRedisCache.search_key("states", limit=5, search="x", parent_id=99)
    result = await geo_redis_cache.get_json(key, resource="states")
    assert result is None
    assert any(msg == "Geo cache miss" and ctx.get("result") == "miss" for msg, ctx in logs)


@pytest.mark.asyncio
async def test_geo_service_cache_aside(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from domains.geo.service import GeoService

    repo = AsyncMock()
    repo.search_countries.return_value = [
        {"id": 2, "iso2": "GB", "iso3": "GBR", "name": "United Kingdom", "phone_code": "44"}
    ]
    cache = GeoRedisCache()
    service = GeoService(repository=repo, cache=cache)

    first = await service.search_countries("united", limit=10)
    second = await service.search_countries("united", limit=10)
    assert first == second
    repo.search_countries.assert_awaited_once()


@pytest.mark.asyncio
async def test_geo_service_list_limit_when_search_empty() -> None:
    from unittest.mock import AsyncMock

    from domains.geo.service import GeoService

    repo = AsyncMock()
    repo.search_countries.return_value = []
    service = GeoService(repository=repo, cache=GeoRedisCache())

    await service.search_countries("", limit=None)

    repo.search_countries.assert_awaited_once()
    assert repo.search_countries.await_args.kwargs["limit"] == 300
