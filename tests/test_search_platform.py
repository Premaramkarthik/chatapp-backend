"""Tests for search cache keys and filter builders."""

from __future__ import annotations

from domains.search.filters import (
    TravelerSearchFilters,
    build_traveler_filters,
    build_viewer_filters,
    combine_filters,
)
from infrastructure.redis.search_cache import SearchRedisCache


def test_build_viewer_filters_excludes_self_and_blocks() -> None:
    clause = build_viewer_filters(
        "11111111-1111-1111-1111-111111111111",
        ["22222222-2222-2222-2222-222222222222"],
    )
    assert "is_searchable:=true" in clause
    assert "id:!=11111111-1111-1111-1111-111111111111" in clause
    assert "id:!=22222222-2222-2222-2222-222222222222" in clause


def test_build_traveler_filters_destination_country() -> None:
    filters = TravelerSearchFilters(destination_country="us", verified=True)
    clause = build_traveler_filters(filters)
    assert "to_country:=US" in clause
    assert "verified:=true" in clause


def test_combine_filters_skips_empty() -> None:
    combined = combine_filters("is_searchable:=true", "", "verified:=true")
    assert combined == "is_searchable:=true && verified:=true"


def test_search_cache_key_is_stable() -> None:
    cache = SearchRedisCache()
    key_a = cache.key_for("global", q="dubai", viewer_id="abc", limit=5)
    key_b = cache.key_for("global", q="dubai", viewer_id="abc", limit=5)
    assert key_a == key_b
    assert key_a.startswith("search:global:")
