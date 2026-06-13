"""In-memory geo dataset models for CSC sync."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CountryRecord:
    """Country row sourced from CSC."""

    iso2: str
    iso3: str
    name: str
    phone_code: str | None


@dataclass(frozen=True, slots=True)
class StateRecord:
    """State row with parent country ISO2 for ID resolution."""

    country_iso2: str
    state_code: str | None
    name: str


@dataclass(frozen=True, slots=True)
class CityRecord:
    """City row with parent keys for state ID resolution."""

    csc_city_id: int
    country_iso2: str
    state_code: str | None
    state_name: str
    name: str


@dataclass(slots=True)
class GeoDataset:
    """Full CSC dataset loaded into memory before persistence."""

    countries: list[CountryRecord] = field(default_factory=list)
    states: list[StateRecord] = field(default_factory=list)
    cities: list[CityRecord] = field(default_factory=list)

    @property
    def country_count(self) -> int:
        return len(self.countries)

    @property
    def state_count(self) -> int:
        return len(self.states)

    @property
    def city_count(self) -> int:
        return len(self.cities)
