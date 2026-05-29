"""Process search_outbox_events and sync Meilisearch."""

from __future__ import annotations

import asyncio

from core.config.settings import settings
from core.logging.logger import get_logger
from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from infrastructure.meilisearch.client import get_meilisearch_client
from infrastructure.meilisearch.sync import delete_traveler, upsert_traveler

logger = get_logger(__name__)


async def process_search_outbox_once(*, batch_size: int = 50) -> int:
    """Process one batch of outbox events. Returns number processed."""
    if not settings.meilisearch.enabled:
        return 0

    repo = PostgresDiscoveryRepository()
    events = await repo.claim_outbox_batch(limit=batch_size)
    if not events:
        return 0

    client = get_meilisearch_client()
    index_uid = settings.meilisearch.traveler_index

    for event in events:
        event_id = str(event["id"])
        user_id = str(event["aggregate_id"])
        try:
            if event["event_type"] == "delete":
                await asyncio.to_thread(delete_traveler, client, index_uid, user_id)
            else:
                snapshot = await repo.get_snapshot(user_id)
                if snapshot is None:
                    await asyncio.to_thread(delete_traveler, client, index_uid, user_id)
                else:
                    await asyncio.to_thread(upsert_traveler, client, index_uid, snapshot)
            await repo.complete_outbox(event_id)
        except Exception as exc:
            logger.warning("search outbox event {} failed: {}", event_id, exc)
            await repo.fail_outbox(event_id, str(exc))

    return len(events)


async def run_search_outbox_loop(stop_event: asyncio.Event, *, interval_sec: float = 5.0) -> None:
    """Background loop until stop_event is set."""
    while not stop_event.is_set():
        try:
            processed = await process_search_outbox_once()
            if processed == 0:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("search outbox loop error: {}", exc)
            await asyncio.sleep(interval_sec)
