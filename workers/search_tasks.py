"""Dramatiq actors for search indexing and analytics."""

from __future__ import annotations

import asyncio

import dramatiq

from core.config.settings import settings
from core.logging.logger import get_logger, log_warning
from core.observability.prometheus_metrics import SEARCH_INDEX_JOBS_TOTAL
from domains.search.outbox_processor import process_outbox_event
from infrastructure.database.repositories.discovery import PostgresDiscoveryRepository
from infrastructure.database.repositories.search_analytics import SearchAnalyticsRepository
from infrastructure.database.repositories.search_index import SearchIndexRepository
from infrastructure.typesense.documents.popular_searches import popular_search_row_to_document
from infrastructure.typesense.documents.travelers import (
    should_index_traveler_snapshot,
    snapshot_to_traveler_document,
)
from infrastructure.typesense.documents.users import user_row_to_document
from infrastructure.typesense.sync import delete_document, upsert_documents
from workers.dramatiq_broker import broker  # noqa: F401

logger = get_logger(__name__)


def _run(coro):
    """Run an async coroutine from a sync Dramatiq actor."""
    return asyncio.run(coro)


@dramatiq.actor(queue_name="search", max_retries=3)
def index_user_document(user_id: str) -> None:
    """Upsert or delete a user search document."""
    if not settings.typesense.enabled:
        return
    try:
        row = _run(SearchIndexRepository().get_user_search_row(user_id))
        collection = settings.typesense.users_collection
        if row is None:
            delete_document(collection, user_id)
            SEARCH_INDEX_JOBS_TOTAL.labels(
                collection=collection, action="delete", outcome="success"
            ).inc()
            return
        doc = user_row_to_document(row)
        if not doc.get("is_searchable"):
            delete_document(collection, user_id)
            SEARCH_INDEX_JOBS_TOTAL.labels(
                collection=collection, action="delete", outcome="success"
            ).inc()
            return
        upsert_documents(collection, [doc])
        SEARCH_INDEX_JOBS_TOTAL.labels(
            collection=collection, action="upsert", outcome="success"
        ).inc()
    except Exception as exc:
        SEARCH_INDEX_JOBS_TOTAL.labels(
            collection=settings.typesense.users_collection,
            action="upsert",
            outcome="error",
        ).inc()
        log_warning(logger, "index_user_document failed", user_id=user_id, error=str(exc))
        raise


@dramatiq.actor(queue_name="search", max_retries=3)
def index_traveler_document(user_id: str) -> None:
    """Upsert or delete a traveler search document."""
    if not settings.typesense.enabled:
        return
    try:
        row = _run(SearchIndexRepository().get_traveler_search_row(user_id))
        collection = settings.typesense.travelers_collection
        if row is None or not should_index_traveler_snapshot(row):
            delete_document(collection, user_id)
            SEARCH_INDEX_JOBS_TOTAL.labels(
                collection=collection, action="delete", outcome="success"
            ).inc()
            return
        doc = snapshot_to_traveler_document(
            row,
            email_verified=bool(row.get("email_verified")),
            profile_completed=bool(row.get("profile_completed")),
        )
        upsert_documents(collection, [doc])
        SEARCH_INDEX_JOBS_TOTAL.labels(
            collection=collection, action="upsert", outcome="success"
        ).inc()
    except Exception as exc:
        SEARCH_INDEX_JOBS_TOTAL.labels(
            collection=settings.typesense.travelers_collection,
            action="upsert",
            outcome="error",
        ).inc()
        log_warning(logger, "index_traveler_document failed", user_id=user_id, error=str(exc))
        raise


@dramatiq.actor(queue_name="search", max_retries=3)
def delete_search_document(collection: str, document_id: str) -> None:
    """Delete a document from a Typesense collection."""
    if not settings.typesense.enabled:
        return
    try:
        delete_document(collection, document_id)
        SEARCH_INDEX_JOBS_TOTAL.labels(
            collection=collection, action="delete", outcome="success"
        ).inc()
    except Exception as exc:
        SEARCH_INDEX_JOBS_TOTAL.labels(
            collection=collection, action="delete", outcome="error"
        ).inc()
        log_warning(
            logger,
            "delete_search_document failed",
            collection=collection,
            document_id=document_id,
            error=str(exc),
        )
        raise


@dramatiq.actor(queue_name="search", max_retries=3)
def record_search_event(
    *,
    user_id: str | None,
    query: str,
    result_type: str,
    result_id: str | None = None,
    clicked: bool = False,
) -> None:
    """Insert a search analytics event."""
    _run(
        SearchAnalyticsRepository().insert_event(
            user_id=user_id,
            query=query,
            result_type=result_type,
            result_id=result_id,
            clicked=clicked,
        )
    )


@dramatiq.actor(queue_name="search", max_retries=3)
def aggregate_popular_searches(*, limit: int = 50) -> None:
    """Roll up analytics into the popular_searches collection."""
    if not settings.typesense.enabled:
        return

    async def _aggregate() -> None:
        rows = await SearchAnalyticsRepository().list_popular_queries(limit=limit)
        docs = [
            popular_search_row_to_document(
                {
                    "id": row["label"],
                    "label": row["label"],
                    "kind": row["kind"],
                    "score": row["score"],
                }
            )
            for row in rows
        ]
        if docs:
            upsert_documents(settings.typesense.popular_searches_collection, docs)

    try:
        _run(_aggregate())
        SEARCH_INDEX_JOBS_TOTAL.labels(
            collection=settings.typesense.popular_searches_collection,
            action="upsert",
            outcome="success",
        ).inc()
    except Exception as exc:
        SEARCH_INDEX_JOBS_TOTAL.labels(
            collection=settings.typesense.popular_searches_collection,
            action="upsert",
            outcome="error",
        ).inc()
        log_warning(logger, "aggregate_popular_searches failed", error=str(exc))
        raise


@dramatiq.actor(queue_name="search", max_retries=3)
def process_outbox_batch(*, batch_size: int = 50) -> int:
    """Claim and process one outbox batch."""
    if not settings.typesense.enabled:
        return 0

    async def _process() -> int:
        repo = PostgresDiscoveryRepository()
        events = await repo.claim_outbox_batch(limit=batch_size)
        for event in events:
            event_id = str(event["id"])
            try:
                await process_outbox_event(event)
                await repo.complete_outbox(event_id)
            except Exception as exc:
                await repo.fail_outbox(event_id, str(exc))
                log_warning(logger, "Outbox event failed", event_id=event_id, error=str(exc))
        return len(events)

    return _run(_process())
