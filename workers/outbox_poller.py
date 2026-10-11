"""Poll search_outbox_events and dispatch Dramatiq indexing tasks."""

from __future__ import annotations

import asyncio

from core.config.settings import settings
from core.logging.logger import get_logger, log_warning
from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from workers.search_tasks import (
    delete_search_document,
    index_traveler_document,
    index_user_document,
)

logger = get_logger(__name__)


def _dispatch_event(event: dict) -> None:
    """Dispatch a single outbox event to the appropriate Dramatiq actor."""
    aggregate_type = str(event.get("aggregate_type") or "")
    user_id = str(event["aggregate_id"])
    event_type = str(event.get("event_type") or "upsert")

    if event_type == "delete":
        if aggregate_type in {"explorer_discovery_snapshot", "traveler"}:
            delete_search_document.send(settings.typesense.travelers_collection, user_id)
        elif aggregate_type == "user":
            delete_search_document.send(settings.typesense.users_collection, user_id)
        return

    if aggregate_type in {"explorer_discovery_snapshot", "traveler"}:
        index_traveler_document.send(user_id)
    elif aggregate_type == "user":
        index_user_document.send(user_id)


async def poll_outbox_once(*, batch_size: int = 50) -> int:
    """Claim one outbox batch and enqueue Dramatiq tasks."""
    if not settings.typesense.enabled:
        return 0

    repo = PostgresDiscoveryRepository()
    events = await repo.claim_outbox_batch(limit=batch_size)
    for event in events:
        event_id = str(event["id"])
        try:
            _dispatch_event(event)
            await repo.complete_outbox(event_id)
        except Exception as exc:
            await repo.fail_outbox(event_id, str(exc))
            log_warning(logger, "Outbox dispatch failed", event_id=event_id, error=str(exc))
    return len(events)


async def run_outbox_poller_loop(
    stop_event: asyncio.Event | None = None,
    *,
    interval_sec: float = 5.0,
) -> None:
    """Background loop claiming outbox rows until stop_event is set."""
    while stop_event is None or not stop_event.is_set():
        try:
            processed = await poll_outbox_once()
            if processed == 0:
                if stop_event is not None:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
                    except TimeoutError:
                        continue
                else:
                    await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_warning(logger, "Outbox poller loop error", error=str(exc))
            await asyncio.sleep(interval_sec)


def main() -> None:
    """CLI entrypoint for the outbox poller process."""
    if not settings.typesense.enabled:
        logger.info("Typesense disabled; outbox poller exiting")
        return
    logger.info("Starting search outbox poller")

    async def _loop() -> None:
        while True:
            await poll_outbox_once()
            await asyncio.sleep(5.0)

    try:
        asyncio.run(_loop())
    except KeyboardInterrupt:
        logger.info("Search outbox poller stopped")


if __name__ == "__main__":
    main()
