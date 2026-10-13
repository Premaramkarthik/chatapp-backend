"""Orchestrate CSC geo sync: load, persist, flush cache, report."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg

from core.config.settings import settings
from core.logging.logger import log_info, logger
from geo_sync.loader import load_csc_dataset
from geo_sync.persistence import persist_dataset
from geo_sync.progress import ProgressReporter, SyncProgress
from geo_sync.redis_manager import flush_geo_cache


@dataclass(frozen=True, slots=True)
class GeoSyncResult:
    """Outcome metrics from a completed geo sync run."""

    countries: int
    states: int
    cities: int
    duration_sec: float
    rows_per_sec: float
    redis_flushed: bool
    redis_keys_deleted: int
    started_at: datetime
    finished_at: datetime


async def run_geo_sync(
    *,
    database_url: str,
    truncate: bool,
    flush_redis: bool,
    limit_countries: int | None,
    chunk_size: int,
    verbose: bool,
) -> GeoSyncResult:
    """Load CSC data, persist to Postgres in one transaction, optionally flush Redis."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    started_at = datetime.now(UTC)
    progress = SyncProgress()
    reporter = ProgressReporter(enabled=True)

    log_info(
        logger,
        "Geo sync started",
        truncate=truncate,
        flush_redis=flush_redis,
        limit_countries=limit_countries,
        chunk_size=chunk_size,
        started_at=started_at.isoformat(),
    )
    print("Geo Sync Started")
    print()

    dataset = await asyncio.to_thread(
        load_csc_dataset,
        limit_countries=limit_countries,
        reporter=reporter,
        progress=progress,
    )

    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            await persist_dataset(
                conn,
                dataset,
                truncate=truncate,
                chunk_size=chunk_size,
                reporter=reporter,
                progress=progress,
            )
    finally:
        await conn.close()

    redis_keys_deleted = 0
    if flush_redis:
        redis_keys_deleted = await flush_geo_cache()

    finished_at = datetime.now(UTC)
    duration_sec = progress.elapsed_sec
    result = GeoSyncResult(
        countries=dataset.country_count,
        states=dataset.state_count,
        cities=dataset.city_count,
        duration_sec=duration_sec,
        rows_per_sec=progress.rows_per_sec,
        redis_flushed=flush_redis,
        redis_keys_deleted=redis_keys_deleted,
        started_at=started_at,
        finished_at=finished_at,
    )

    log_info(
        logger,
        "Geo sync completed",
        countries_synced=result.countries,
        states_synced=result.states,
        cities_synced=result.cities,
        duration_sec=round(result.duration_sec, 2),
        rows_per_sec=round(result.rows_per_sec, 1),
        redis_keys_flushed=result.redis_keys_deleted if flush_redis else 0,
        finished_at=finished_at.isoformat(),
    )

    if verbose:
        log_info(
            logger,
            "Geo sync throughput",
            countries_loaded=progress.countries_loaded,
            states_loaded=progress.states_loaded,
            cities_loaded=progress.cities_loaded,
            cities_written=progress.cities_written,
        )

    return result


async def main_async(args) -> int:
    """Entry point for sync_geo_from_csc script."""
    database_url = args.database_url or settings.database.direct_dsn
    result = await run_geo_sync(
        database_url=database_url,
        truncate=args.truncate,
        flush_redis=args.flush_redis,
        limit_countries=args.limit_countries,
        chunk_size=args.chunk_size,
        verbose=args.verbose,
    )

    ProgressReporter.print_summary(
        countries=result.countries,
        states=result.states,
        cities=result.cities,
        duration_sec=result.duration_sec,
        redis_flushed=result.redis_flushed,
        redis_keys_deleted=result.redis_keys_deleted,
    )
    return 0
