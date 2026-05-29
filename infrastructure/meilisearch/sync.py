"""Meilisearch upsert/delete for traveler documents."""

from __future__ import annotations

from typing import Any

from meilisearch import Client

from infrastructure.meilisearch.traveler_documents import (
    should_index_snapshot,
    snapshot_to_meili_document,
)


def upsert_traveler(client: Client, index_uid: str, row: dict[str, Any]) -> None:
    """Index one traveler document (stable primary key = user id)."""
    if not should_index_snapshot(row):
        delete_traveler(client, index_uid, str(row["user_id"]))
        return
    doc = snapshot_to_meili_document(row)
    client.index(index_uid).add_documents([doc], primary_key="id")


def delete_traveler(client: Client, index_uid: str, user_id: str) -> None:
    """Remove a traveler from the index."""
    client.index(index_uid).delete_document(str(user_id))
