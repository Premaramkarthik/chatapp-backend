"""PostgreSQL bulk persistence for geo master tables."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import asyncpg

from geo_sync.models import CityRecord, CountryRecord, GeoDataset, StateRecord
from geo_sync.progress import ProgressReporter, SyncProgress

COUNTRY_COLUMNS = ("iso2", "iso3", "name", "phone_code")
STATE_COLUMNS = ("country_id", "state_code", "name")
CITY_COLUMNS = ("csc_city_id", "country_id", "state_id", "name")


async def truncate_master(conn: asyncpg.Connection) -> None:
    """Remove all geo master rows and reset sequences."""
    await conn.execute("TRUNCATE geo_cities, geo_states, geo_countries RESTART IDENTITY CASCADE")


def _country_tuples(countries: Sequence[CountryRecord]) -> list[tuple[Any, ...]]:
    return [(c.iso2, c.iso3, c.name, c.phone_code) for c in countries]


def _state_tuples(
    states: Sequence[StateRecord],
    country_ids: dict[str, int],
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for state in states:
        country_id = country_ids[state.country_iso2]
        rows.append((country_id, state.state_code, state.name))
    return rows


def _state_lookup_key(
    country_id: int,
    state_code: str | None,
    state_name: str,
) -> tuple[int, str | None, str]:
    """Build lookup key for state id map (code-first, name fallback)."""
    return (country_id, state_code, state_name)


def _city_tuples(
    cities: Sequence[CityRecord],
    country_ids: dict[str, int],
    state_ids: dict[tuple[int, str | None, str], int],
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for city in cities:
        country_id = country_ids[city.country_iso2]
        state_id = state_ids[_state_lookup_key(country_id, city.state_code, city.state_name)]
        rows.append((city.csc_city_id, country_id, state_id, city.name))
    return rows


def _chunked(items: Sequence[tuple[Any, ...]], size: int) -> Iterator[list[tuple[Any, ...]]]:
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


async def _copy_rows(
    conn: asyncpg.Connection,
    table: str,
    columns: Sequence[str],
    rows: Sequence[tuple[Any, ...]],
) -> None:
    if not rows:
        return
    await conn.copy_records_to_table(table, records=rows, columns=list(columns))


async def _fetch_country_ids(conn: asyncpg.Connection) -> dict[str, int]:
    records = await conn.fetch("SELECT id, iso2 FROM geo_countries")
    return {row["iso2"]: int(row["id"]) for row in records}


async def _fetch_state_ids(conn: asyncpg.Connection) -> dict[tuple[int, str | None, str], int]:
    records = await conn.fetch("SELECT id, country_id, state_code, name FROM geo_states")
    mapping: dict[tuple[int, str | None, str], int] = {}
    for row in records:
        key = _state_lookup_key(
            int(row["country_id"]),
            row["state_code"],
            row["name"],
        )
        mapping[key] = int(row["id"])
    return mapping


async def _upsert_countries(
    conn: asyncpg.Connection,
    countries: Sequence[CountryRecord],
) -> None:
    await conn.execute(
        """
        CREATE TEMP TABLE geo_countries_staging (
            iso2 CHAR(2) NOT NULL,
            iso3 CHAR(3) NOT NULL,
            name VARCHAR(100) NOT NULL,
            phone_code VARCHAR(20)
        ) ON COMMIT DROP
        """
    )
    await _copy_rows(conn, "geo_countries_staging", COUNTRY_COLUMNS, _country_tuples(countries))
    await conn.execute(
        """
        INSERT INTO geo_countries (iso2, iso3, name, phone_code)
        SELECT iso2, iso3, name, phone_code
        FROM geo_countries_staging
        ON CONFLICT (iso2) DO UPDATE SET
            iso3 = EXCLUDED.iso3,
            name = EXCLUDED.name,
            phone_code = EXCLUDED.phone_code
        """
    )


async def _upsert_states(
    conn: asyncpg.Connection,
    states: Sequence[StateRecord],
    country_ids: dict[str, int],
) -> None:
    await conn.execute(
        """
        CREATE TEMP TABLE geo_states_staging (
            country_id BIGINT NOT NULL,
            state_code VARCHAR(20),
            name VARCHAR(100) NOT NULL
        ) ON COMMIT DROP
        """
    )
    await _copy_rows(conn, "geo_states_staging", STATE_COLUMNS, _state_tuples(states, country_ids))
    await conn.execute(
        """
        INSERT INTO geo_states (country_id, state_code, name)
        SELECT country_id, state_code, name
        FROM geo_states_staging
        WHERE state_code IS NOT NULL
        ON CONFLICT (country_id, state_code) WHERE state_code IS NOT NULL
        DO UPDATE SET name = EXCLUDED.name
        """
    )
    await conn.execute(
        """
        INSERT INTO geo_states (country_id, state_code, name)
        SELECT s.country_id, s.state_code, s.name
        FROM geo_states_staging s
        WHERE s.state_code IS NULL
          AND NOT EXISTS (
              SELECT 1
              FROM geo_states g
              WHERE g.country_id = s.country_id
                AND g.state_code IS NULL
                AND g.name = s.name
          )
        """
    )


_CITIES_STAGING_DDL = """
CREATE TEMP TABLE IF NOT EXISTS geo_cities_staging (
    csc_city_id BIGINT NOT NULL,
    country_id BIGINT NOT NULL,
    state_id BIGINT NOT NULL,
    name VARCHAR(150) NOT NULL
) ON COMMIT DROP
"""

_CITIES_UPSERT_SQL = """
INSERT INTO geo_cities (csc_city_id, country_id, state_id, name)
SELECT csc_city_id, country_id, state_id, name
FROM geo_cities_staging
ON CONFLICT (csc_city_id) DO UPDATE SET
    country_id = EXCLUDED.country_id,
    state_id = EXCLUDED.state_id,
    name = EXCLUDED.name
"""


async def _upsert_cities_batched(
    conn: asyncpg.Connection,
    city_rows: Sequence[tuple[Any, ...]],
    *,
    chunk_size: int,
    reporter: ProgressReporter,
    progress: SyncProgress,
) -> None:
    """Upsert cities in chunks via a reusable staging table."""
    await conn.execute(_CITIES_STAGING_DDL)
    write_bar = reporter.city_write_bar(len(city_rows))
    with write_bar:
        for chunk in _chunked(city_rows, chunk_size):
            await conn.execute("TRUNCATE geo_cities_staging")
            await _copy_rows(conn, "geo_cities_staging", CITY_COLUMNS, chunk)
            await conn.execute(_CITIES_UPSERT_SQL)
            write_bar.update(len(chunk))
            progress.cities_written += len(chunk)


async def persist_dataset(
    conn: asyncpg.Connection,
    dataset: GeoDataset,
    *,
    truncate: bool,
    chunk_size: int,
    reporter: ProgressReporter,
    progress: SyncProgress,
) -> None:
    """Bulk load or upsert geo master data inside the caller's transaction."""
    if truncate:
        await truncate_master(conn)
        await _copy_rows(
            conn,
            "geo_countries",
            COUNTRY_COLUMNS,
            _country_tuples(dataset.countries),
        )
        country_ids = await _fetch_country_ids(conn)
        await _copy_rows(
            conn,
            "geo_states",
            STATE_COLUMNS,
            _state_tuples(dataset.states, country_ids),
        )
        state_ids = await _fetch_state_ids(conn)
        city_rows = _city_tuples(dataset.cities, country_ids, state_ids)
        write_bar = reporter.city_write_bar(len(city_rows))
        with write_bar:
            for chunk in _chunked(city_rows, chunk_size):
                await _copy_rows(conn, "geo_cities", CITY_COLUMNS, chunk)
                write_bar.update(len(chunk))
                progress.cities_written += len(chunk)
        return

    await _upsert_countries(conn, dataset.countries)
    country_ids = await _fetch_country_ids(conn)
    await _upsert_states(conn, dataset.states, country_ids)
    state_ids = await _fetch_state_ids(conn)
    city_rows = _city_tuples(dataset.cities, country_ids, state_ids)
    await _upsert_cities_batched(
        conn,
        city_rows,
        chunk_size=chunk_size,
        reporter=reporter,
        progress=progress,
    )
