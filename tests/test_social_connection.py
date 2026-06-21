"""Social connection domain and Typesense mapping tests."""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from domains.matching.policies import (
    CONNECTION_REQUIRES_MUTUAL_ACCEPT,
    SEARCH_PRIMARY_FIELD,
)
from domains.search.filters import TravelerSearchFilters, build_traveler_filters
from infrastructure.database.jsonb_helpers import (
    list_from_jsonb,
    map_social_db_error,
    row_from_jsonb,
)
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.typesense.documents.travelers import (
    should_index_traveler_snapshot,
    snapshot_to_traveler_document,
)


def test_row_from_jsonb_none_and_dict() -> None:
    assert row_from_jsonb(None) is None
    assert row_from_jsonb({"id": "x"}) == {"id": "x"}


def test_list_from_jsonb_empty_and_array() -> None:
    assert list_from_jsonb(None) == []
    assert list_from_jsonb([{"a": 1}]) == [{"a": 1}]


def test_map_social_db_error_messages() -> None:
    with pytest.raises(ValueError, match="blocked"):
        map_social_db_error(Exception("ERROR: blocked"))
    with pytest.raises(ValueError, match="not_found"):
        map_social_db_error(Exception("P0001: not_found"))


@pytest.mark.asyncio
async def test_matching_repo_create_request_calls_fn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int, dict[str, Any]]] = []

    async def fake_call(function_name: str, mode: int, payload: dict[str, Any]) -> Any:
        calls.append((function_name, mode, payload))
        if function_name == "fn_connection_requests" and mode == 1:
            return {"id": "req-1", "status": "pending"}
        raise AssertionError((function_name, mode, payload))

    monkeypatch.setattr(
        "infrastructure.database.repositories.matching.call_json_function",
        fake_call,
    )
    repo = PostgresMatchingRepository()
    row = await repo.create_connection_request("u1", "u2", "hi")
    assert row["id"] == "req-1"
    assert calls[0][0] == "fn_connection_requests"
    assert calls[0][1] == 1
    assert calls[0][2]["requester_id"] == "u1"


@pytest.mark.asyncio
async def test_matching_repo_blocked_maps_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(function_name: str, mode: int, payload: dict[str, Any]) -> Any:
        raise Exception("blocked")

    monkeypatch.setattr(
        "infrastructure.database.repositories.matching.call_json_function",
        fake_call,
    )
    repo = PostgresMatchingRepository()
    with pytest.raises(ValueError, match="blocked"):
        await repo.create_connection_request("u1", "u2", None)


def test_connection_policies_locked() -> None:
    assert CONNECTION_REQUIRES_MUTUAL_ACCEPT is True
    assert SEARCH_PRIMARY_FIELD == "destination_country"


def test_snapshot_to_traveler_document_includes_fields() -> None:
    row = {
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "display_name": "Alex",
        "headline": "Exploring",
        "destination_country_iso": "US",
        "current_country_iso": "GB",
        "destination_city_id": None,
        "destination_city_name": "New York",
        "current_city_name": "London",
        "connection_availability": "open",
        "visibility": "discoverable",
        "languages": ["en"],
        "interests": ["hiking"],
        "last_active_at": datetime(2026, 1, 1, tzinfo=UTC),
        "trip_start_date": date(2026, 2, 1),
        "trip_end_date": date(2026, 3, 1),
        "geo_lat": 40.7,
        "geo_lng": -74.0,
        "is_discoverable": True,
    }
    doc = snapshot_to_traveler_document(row, email_verified=True, profile_completed=True)
    assert doc["id"] == row["user_id"]
    assert doc["to_country"] == "US"
    assert doc["from_country"] == "GB"
    assert doc["to_city"] == "New York"
    assert doc["verified"] is True
    assert doc["is_searchable"] is True


def test_should_index_traveler_snapshot() -> None:
    assert should_index_traveler_snapshot({"is_discoverable": True, "visibility": "discoverable"})
    assert not should_index_traveler_snapshot(
        {"is_discoverable": False, "visibility": "discoverable"}
    )
    assert not should_index_traveler_snapshot({"is_discoverable": True, "visibility": "hidden"})


def test_snapshot_custom_city_name_mapped() -> None:
    row = {
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "display_name": "Alex",
        "headline": "Exploring",
        "destination_country_iso": None,
        "destination_city_id": None,
        "destination_city_name": "Kothavalasa",
        "current_country_iso": None,
        "connection_availability": "open",
        "visibility": "discoverable",
        "languages": ["en"],
        "interests": [],
        "last_active_at": None,
        "trip_start_date": None,
        "trip_end_date": None,
        "geo_lat": None,
        "geo_lng": None,
        "is_discoverable": True,
    }
    doc = snapshot_to_traveler_document(row)
    assert doc["to_city"] == "Kothavalasa"


def test_build_traveler_filters_destination_and_current_country() -> None:
    query = TravelerSearchFilters(
        destination_country="us",
        current_country="gb",
        city_id="101",
    )
    filt = build_traveler_filters(query)
    assert "to_country:=US" in filt
    assert "from_country:=GB" in filt
    assert "to_city:=101" in filt
