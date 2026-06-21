"""Process search_outbox_events and sync Typesense via Dramatiq."""

from __future__ import annotations

from core.config.settings import settings
from core.logging.logger import get_logger, log_warning
from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from infrastructure.database.repositories.search_index import SearchIndexRepository
from infrastructure.typesense.documents.travelers import (
    should_index_traveler_snapshot,
    snapshot_to_traveler_document,
)
from infrastructure.typesense.documents.users import user_row_to_document
from infrastructure.typesense.sync import delete_document, upsert_documents

logger = get_logger(__name__)


def _collection_for_aggregate(aggregate_type: str) -> str | None:
    """Map outbox aggregate_type to Typesense collection name."""
    mapping = {
        "explorer_discovery_snapshot": settings.typesense.travelers_collection,
        "traveler": settings.typesense.travelers_collection,
        "user": settings.typesense.users_collection,
    }
    return mapping.get(aggregate_type)


async def process_outbox_event(event: dict) -> None:
    """Process a single outbox event into Typesense."""
    if not settings.typesense.enabled:
        return

    aggregate_type = str(event.get("aggregate_type") or "")
    collection = _collection_for_aggregate(aggregate_type)
    if collection is None:
        log_warning(
            logger,
            "Unknown search outbox aggregate type",
            aggregate_type=aggregate_type,
            event_id=str(event.get("id")),
        )
        return

    user_id = str(event["aggregate_id"])
    event_type = str(event.get("event_type") or "upsert")

    if event_type == "delete":
        delete_document(collection, user_id)
        return

    if collection == settings.typesense.travelers_collection:
        repo = PostgresDiscoveryRepository()
        snapshot = await repo.get_snapshot(user_id)
        if snapshot is None or not should_index_traveler_snapshot(snapshot):
            delete_document(collection, user_id)
            return
        index_repo = SearchIndexRepository()
        enriched = await index_repo.get_traveler_search_row(user_id)
        row = enriched or snapshot
        doc = snapshot_to_traveler_document(
            row,
            email_verified=bool(row.get("email_verified")),
            profile_completed=bool(row.get("profile_completed")),
        )
        upsert_documents(collection, [doc])
        return

    if collection == settings.typesense.users_collection:
        index_repo = SearchIndexRepository()
        row = await index_repo.get_user_search_row(user_id)
        if row is None:
            delete_document(collection, user_id)
            return
        doc = user_row_to_document(row)
        if not doc.get("is_searchable"):
            delete_document(collection, user_id)
            return
        upsert_documents(collection, [doc])
