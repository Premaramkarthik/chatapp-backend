"""Typesense upsert/delete helpers."""

from __future__ import annotations

import json
from typing import Any

from infrastructure.typesense.client import get_typesense_client


def upsert_documents(
    collection: str,
    documents: list[dict[str, Any]],
    *,
    batch_size: int = 100,
) -> int:
    """Bulk upsert documents via import_ with action=upsert."""
    if not documents:
        return 0
    client = get_typesense_client()
    result = client.collections[collection].documents.import_(
        documents,
        {"action": "upsert", "batch_size": batch_size},
    )
    if isinstance(result, str):
        lines = [line for line in result.strip().split("\n") if line]
        return sum(1 for line in lines if json.loads(line).get("success", False))
    return len(documents)


def delete_document(collection: str, document_id: str) -> None:
    """Delete a single document by id."""
    client = get_typesense_client()
    client.collections[collection].documents[str(document_id)].delete()
