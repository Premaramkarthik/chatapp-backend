"""Location payload validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domains.geo.location_payload import LocationFields, normalize_home_location_payload
from v1.schemas.travelers import CurrentLocationUpdateRequest, TravelPlanDestinationInput


def test_mutual_exclusion_city_id_vs_custom() -> None:
    with pytest.raises(ValidationError):
        LocationFields(city_id=1, custom_city_name="Kothavalasa")


def test_custom_city_with_master_country_state() -> None:
    fields = LocationFields(country_id=1, state_id=101, custom_city_name="Kothavalasa")
    assert fields.city_id is None
    assert fields.custom_city_name == "Kothavalasa"


def test_normalize_home_location_payload() -> None:
    payload = normalize_home_location_payload(
        home_country_id=1,
        home_state_id=2,
        custom_home_city_name="Village",
    )
    assert payload == {
        "home_country_id": 1,
        "home_state_id": 2,
        "custom_home_city_name": "Village",
    }


def test_trip_destination_accepts_custom_city() -> None:
    dest = TravelPlanDestinationInput(
        country_id=1,
        state_id=2,
        custom_city_name="Kothavalasa",
    )
    assert dest.city_id is None


def test_current_location_rejects_empty_custom_string() -> None:
    with pytest.raises(ValidationError):
        CurrentLocationUpdateRequest(custom_city_name="   ")
