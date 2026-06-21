"""Bulk Typesense reindex CLI."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config.settings import settings  # noqa: E402
from core.logging.logger import get_logger  # noqa: E402
from core.observability.prometheus_metrics import SEARCH_REINDEX_DURATION_SECONDS  # noqa: E402
from infrastructure.database.connection import close_db, init_db  # noqa: E402
from infrastructure.database.repositories.search_index import SearchIndexRepository  # noqa: E402
from infrastructure.typesense.collections import ensure_all_collections  # noqa: E402
from infrastructure.typesense.documents.cities import city_row_to_document  # noqa: E402
from infrastructure.typesense.documents.countries import country_row_to_document  # noqa: E402
from infrastructure.typesense.documents.states import state_row_to_document  # noqa: E402
from infrastructure.typesense.documents.travelers import (  # noqa: E402
    should_index_traveler_snapshot,
    snapshot_to_traveler_document,
)
from infrastructure.typesense.documents.users import user_row_to_document  # noqa: E402
from infrastructure.typesense.health import health  # noqa: E402
from infrastructure.typesense.sync import upsert_documents  # noqa: E402

logger = get_logger(__name__)

COLLECTIONS = ("users", "travelers", "cities", "countries", "states", "popular_searches", "all")


async def _reindex_users(*, batch_size: int) -> int:
    total = 0
    repo = SearchIndexRepository()
    collection = settings.typesense.users_collection
    async for batch in repo.stream_users(batch_size=batch_size):
        docs = [
            user_row_to_document(row)
            for row in batch
            if user_row_to_document(row).get("is_searchable")
        ]
        if docs:
            total += upsert_documents(collection, docs, batch_size=batch_size)
    return total


async def _reindex_travelers(*, batch_size: int) -> int:
    total = 0
    repo = SearchIndexRepository()
    collection = settings.typesense.travelers_collection
    async for batch in repo.stream_travelers(batch_size=batch_size):
        docs = []
        for row in batch:
            if not should_index_traveler_snapshot(row):
                continue
            docs.append(
                snapshot_to_traveler_document(
                    row,
                    email_verified=bool(row.get("email_verified")),
                    profile_completed=bool(row.get("profile_completed")),
                )
            )
        if docs:
            total += upsert_documents(collection, docs, batch_size=batch_size)
    return total


async def _reindex_cities(*, batch_size: int) -> int:
    total = 0
    repo = SearchIndexRepository()
    collection = settings.typesense.cities_collection
    async for batch in repo.stream_cities(batch_size=batch_size):
        docs = [city_row_to_document(row) for row in batch]
        total += upsert_documents(collection, docs, batch_size=batch_size)
    return total


async def _reindex_countries(*, batch_size: int) -> int:
    total = 0
    repo = SearchIndexRepository()
    collection = settings.typesense.countries_collection
    async for batch in repo.stream_countries(batch_size=batch_size):
        docs = [country_row_to_document(row) for row in batch]
        total += upsert_documents(collection, docs, batch_size=batch_size)
    return total


async def _reindex_states(*, batch_size: int) -> int:
    total = 0
    repo = SearchIndexRepository()
    collection = settings.typesense.states_collection
    async for batch in repo.stream_states(batch_size=batch_size):
        docs = [state_row_to_document(row) for row in batch]
        total += upsert_documents(collection, docs, batch_size=batch_size)
    return total


async def rebuild_collection(collection: str, *, batch_size: int) -> int:
    """Rebuild a single collection or all collections."""
    if collection == "users":
        return await _reindex_users(batch_size=batch_size)
    if collection == "travelers":
        return await _reindex_travelers(batch_size=batch_size)
    if collection == "cities":
        return await _reindex_cities(batch_size=batch_size)
    if collection == "countries":
        return await _reindex_countries(batch_size=batch_size)
    if collection == "states":
        return await _reindex_states(batch_size=batch_size)
    if collection == "popular_searches":
        logger.info("popular_searches is populated by aggregate_popular_searches worker")
        return 0
    if collection == "all":
        total = 0
        for name in ("countries", "states", "cities", "users", "travelers"):
            total += await rebuild_collection(name, batch_size=batch_size)
        return total
    raise ValueError(f"Unknown collection: {collection}")


async def main_async(args: argparse.Namespace) -> int:
    """Run rebuild for the requested collection."""
    if not settings.typesense.enabled:
        logger.error("TYPESENSE_ENABLED is false; aborting rebuild")
        return 1
    ts = settings.typesense
    ts_health = await health()
    if not ts_health.ok:
        logger.error(
            "Typesense is not reachable; start it with `docker compose up -d typesense` "
            "then retry",
            typesense_url=f"{ts.protocol}://{ts.host}:{ts.port}",
            detail=ts_health.detail,
        )
        return 1
    await init_db()
    started = time.perf_counter()
    try:
        ensure_all_collections()
        count = await rebuild_collection(args.collection, batch_size=args.batch_size)
    finally:
        await close_db()
    duration = time.perf_counter() - started
    SEARCH_REINDEX_DURATION_SECONDS.labels(collection=args.collection).observe(duration)
    logger.info(
        "Search reindex completed",
        collection=args.collection,
        documents=count,
        duration_sec=round(duration, 2),
    )
    return 0


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Rebuild Typesense search indexes from Postgres")
    parser.add_argument(
        "--collection",
        choices=COLLECTIONS,
        default="all",
        help="Collection to rebuild (default: all)",
    )
    parser.add_argument("--batch-size", type=int, default=500, help="Bulk import batch size")
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint."""
    raise SystemExit(asyncio.run(main_async(parse_args())))


if __name__ == "__main__":
    main()
