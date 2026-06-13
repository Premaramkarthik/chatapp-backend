"""Load CSC SDK data into memory."""

from __future__ import annotations

from countrystatecity_countries import get_cities_of_state, get_countries, get_states_of_country

from geo_sync.models import CityRecord, CountryRecord, GeoDataset, StateRecord
from geo_sync.progress import ProgressReporter, SyncProgress


def load_csc_dataset(
    *,
    limit_countries: int | None,
    reporter: ProgressReporter,
    progress: SyncProgress,
) -> GeoDataset:
    """Fetch all countries, states, and cities from CSC into memory."""
    raw_countries = get_countries()
    if limit_countries is not None:
        raw_countries = raw_countries[:limit_countries]

    dataset = GeoDataset()
    states_by_country: dict[str, list] = {}

    with reporter.country_bar(len(raw_countries)) as country_bar:
        for country in raw_countries:
            dataset.countries.append(
                CountryRecord(
                    iso2=country.iso2,
                    iso3=country.iso3,
                    name=country.name,
                    phone_code=country.phone_code or None,
                )
            )
            country_bar.update(1)
            progress.countries_loaded += 1

    with reporter.state_bar() as state_bar:
        for country in raw_countries:
            states = get_states_of_country(country.iso2)
            states_by_country[country.iso2] = states
            for state in states:
                dataset.states.append(
                    StateRecord(
                        country_iso2=country.iso2,
                        state_code=state.state_code or None,
                        name=state.name,
                    )
                )
                state_bar.update(1)
                progress.states_loaded += 1

    with reporter.city_load_bar() as city_bar:
        for country in raw_countries:
            for state in states_by_country[country.iso2]:
                for city in get_cities_of_state(country.iso2, state.state_code):
                    dataset.cities.append(
                        CityRecord(
                            csc_city_id=int(city.id),
                            country_iso2=country.iso2,
                            state_code=state.state_code or None,
                            state_name=state.name,
                            name=city.name,
                        )
                    )
                    city_bar.update(1)
                    progress.cities_loaded += 1

    dataset.cities = dedupe_cities_by_csc_id(dataset.cities)

    return dataset


def dedupe_cities_by_csc_id(cities: list[CityRecord]) -> list[CityRecord]:
    """Keep one row per CSC city id (dataset repeats ids across state hierarchies)."""
    seen: set[int] = set()
    unique: list[CityRecord] = []
    for city in cities:
        if city.csc_city_id in seen:
            continue
        seen.add(city.csc_city_id)
        unique.append(city)
    return unique
