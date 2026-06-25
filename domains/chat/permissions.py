"""Conversation permission rules for chat inbox and detail responses."""

from __future__ import annotations

from typing import Any, Literal

InboxStatusFilter = Literal["active", "archived", "all"]


def is_provisioned_room_id(room_id: str | None) -> bool:
    """Return True when room_id is a real Synapse room (not a pending placeholder)."""
    rid = str(room_id or "")
    return rid.startswith("!") and not rid.startswith("!pending_")


def mapping_allows_chat(
    mapping_status: str | None,
    room_id: str | None,
    *,
    blocked: bool = False,
) -> bool:
    """Return whether the shared room mapping allows chat (independent of user archive)."""
    if blocked:
        return False
    status = mapping_status or "provisioning"
    if status != "active":
        return False
    return is_provisioned_room_id(room_id)


def conversation_permissions(
    *,
    mapping_status: str | None,
    can_chat: bool,
    has_mapping: bool,
    is_user_archived: bool = False,
) -> dict[str, Any]:
    """Return normalized permission fields for a conversation mapping."""
    status = mapping_status or "provisioning"
    if status == "archived":
        status = "active"
    return {
        "status": status,
        "can_chat": can_chat,
        "is_archived": is_user_archived,
        "can_archive": has_mapping and not is_user_archived,
        "can_reopen": has_mapping and is_user_archived,
    }


def enrich_inbox_row(row: dict[str, Any]) -> dict[str, Any]:
    """Attach permission fields to an inbox SQL row."""
    mapping = row.get("mapping") or {}
    mapping_status = mapping.get("status") if isinstance(mapping, dict) else None
    is_user_archived = bool(row.get("is_user_archived"))
    perms = conversation_permissions(
        mapping_status=mapping_status,
        can_chat=bool(row.get("can_chat")),
        has_mapping=bool(mapping),
        is_user_archived=is_user_archived,
    )
    return {**row, **perms}


def enrich_mapping_row(
    row: dict[str, Any],
    *,
    can_chat: bool | None = None,
    is_user_archived: bool = False,
) -> dict[str, Any]:
    """Attach permission fields to a mapping row."""
    resolved_can_chat = can_chat
    if resolved_can_chat is None:
        resolved_can_chat = mapping_allows_chat(row.get("status"), row.get("room_id"))
    perms = conversation_permissions(
        mapping_status=row.get("status"),
        can_chat=bool(resolved_can_chat),
        has_mapping=True,
        is_user_archived=is_user_archived,
    )
    return {**row, **perms}


def assert_can_chat(permissions: dict[str, Any]) -> None:
    """Raise ValueError when conversation is not eligible for chat actions."""
    if not permissions.get("can_chat"):
        raise ValueError("Conversation is not active for chat")
