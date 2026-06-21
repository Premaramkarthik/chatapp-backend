"""Chat conversation routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.config.settings import settings
from core.observability.prometheus_metrics import (
    MATRIX_MEDIA_FAILED_TOTAL,
    MATRIX_MEDIA_UPLOAD_TOTAL,
)
from domains.matrix.encryption.service import matrix_encryption_service
from domains.matrix.events.service import matrix_business_event_service
from domains.matrix.moderation.rate_limit import matrix_rate_limiter
from domains.matrix.notifications.service import matrix_notification_service
from domains.matrix.rooms.service import matrix_room_service
from domains.matrix.search.service import matrix_search_service
from domains.matrix.session.service import MatrixSessionNotReadyError, matrix_session_service
from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import row_from_jsonb
from infrastructure.database.repositories.conversations import PostgresConversationRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.auth import get_current_principal, require_capability
from v1.schemas.chat import (
    AttachmentMetadataRequest,
    AttachmentMetadataResponse,
    BusinessEventPublishRequest,
    ConversationMappingSummary,
    ConversationResponse,
    CrossSigningStatusRequest,
    DeviceVerifyRequest,
    InboxItem,
    InboxPeer,
    InboxResponse,
    KeyBackupInitRequest,
    MatrixDeviceResponse,
    MatrixDevicesResponse,
    MatrixSessionResponse,
    NotificationPreferencesPatchRequest,
    NotificationPreferencesResponse,
    RoomSettingsPatchRequest,
    RoomSettingsResponse,
)
from v1.schemas.principal import KeycloakPrincipal
from v1.utils.request_context import request_id_from

router = APIRouter(prefix="/v1/chat", tags=["chat"])
CurrentPrincipal = Annotated[KeycloakPrincipal, Depends(get_current_principal)]
MessageSender = Annotated[KeycloakPrincipal, Depends(require_capability("message:send"))]


async def _local_user(principal: KeycloakPrincipal) -> dict:
    user = await PostgresUserRepository().get_by_keycloak_sub(principal.sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.to_dict()


async def _require_active_connection(connection_id: str, user_id: str) -> dict:
    connection = await PostgresMatchingRepository().get_connection(connection_id)
    if connection is None or connection.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    if user_id not in (str(connection["user_a_id"]), str(connection["user_b_id"])):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a connection member")
    if await PostgresMatchingRepository().is_blocked(
        user_id,
        (
            str(connection["user_b_id"])
            if user_id == str(connection["user_a_id"])
            else str(connection["user_a_id"])
        ),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User blocked")
    return connection


def _mapping_response(row: dict) -> ConversationResponse:
    return ConversationResponse(
        id=row["id"],
        user_connection_id=row["user_connection_id"],
        room_id=row["room_id"],
        room_alias=row.get("room_alias"),
        room_type=row.get("room_type", "dm"),
        status=row["status"],
        business_context=row.get("business_context"),
        created_at=row["created_at"],
        updated_at=row.get("updated_at"),
    )


@router.get("/inbox", response_model=InboxResponse, summary="List 1:1 chat-eligible connections")
async def chat_inbox(_: MessageSender, principal: CurrentPrincipal) -> InboxResponse:
    user = await _local_user(principal)
    rows = await PostgresConversationRepository().list_inbox(user["id"])
    items = [
        InboxItem(
            connection_id=row["connection_id"],
            connection_status=row["connection_status"],
            connected_at=row.get("connected_at"),
            peer=InboxPeer(**row["peer"]),
            mapping=(ConversationMappingSummary(**row["mapping"]) if row.get("mapping") else None),
            can_chat=bool(row.get("can_chat")),
        )
        for row in rows
    ]
    return InboxResponse(items=items)


@router.get(
    "/conversations/{connection_id}",
    response_model=ConversationResponse,
    summary="Get conversation mapping for a connection",
)
async def get_conversation(
    connection_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> ConversationResponse:
    user = await _local_user(principal)
    await _require_active_connection(str(connection_id), user["id"])
    mapping = await PostgresConversationRepository().get_by_connection(str(connection_id))
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    return _mapping_response(mapping)


@router.post(
    "/conversations/{connection_id}/archive",
    response_model=ConversationResponse,
    summary="Archive conversation mapping",
)
async def archive_conversation(
    connection_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> ConversationResponse:
    user = await _local_user(principal)
    await _require_active_connection(str(connection_id), user["id"])
    try:
        mapping = await matrix_room_service.archive_for_connection(
            connection_id=str(connection_id),
            archived_by_user_id=user["id"],
            reason="user_archive",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found"
        ) from exc
    return _mapping_response(mapping)


@router.post(
    "/conversations/{connection_id}/reopen",
    response_model=ConversationResponse,
    summary="Reopen archived conversation",
)
async def reopen_conversation(
    connection_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> ConversationResponse:
    user = await _local_user(principal)
    await _require_active_connection(str(connection_id), user["id"])
    try:
        mapping = await matrix_room_service.reopen_for_connection(connection_id=str(connection_id))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found"
        ) from exc
    return _mapping_response(mapping)


@router.get(
    "/matrix/session", response_model=MatrixSessionResponse, summary="Get Matrix client session"
)
async def get_matrix_session(
    request: Request,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> MatrixSessionResponse:
    user = await _local_user(principal)
    try:
        session = await matrix_session_service.create_session(
            user=user,
            request_id=request_id_from(request),
        )
    except MatrixSessionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return MatrixSessionResponse(enabled=True, **session)


@router.post(
    "/matrix/session", response_model=MatrixSessionResponse, summary="Create Matrix session"
)
async def create_matrix_session(
    request: Request,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> MatrixSessionResponse:
    return await get_matrix_session(request, _, principal)


@router.post(
    "/matrix/session/refresh",
    response_model=MatrixSessionResponse,
    summary="Refresh Matrix session",
)
async def refresh_matrix_session(
    request: Request,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> MatrixSessionResponse:
    user = await _local_user(principal)
    try:
        session = await matrix_session_service.refresh_session(
            user=user,
            request_id=request_id_from(request),
        )
    except MatrixSessionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return MatrixSessionResponse(enabled=True, **session)


@router.get("/devices", response_model=MatrixDevicesResponse, summary="List Matrix devices")
async def list_devices(_: MessageSender, principal: CurrentPrincipal) -> MatrixDevicesResponse:
    user = await _local_user(principal)
    rows = await matrix_encryption_service.list_devices(user["id"])
    return MatrixDevicesResponse(items=[MatrixDeviceResponse(**row) for row in rows])


@router.delete(
    "/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke device"
)
async def revoke_device(
    device_id: str,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> None:
    user = await _local_user(principal)
    deleted = await matrix_encryption_service.delete_device(user_id=user["id"], device_id=device_id)
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")


@router.post("/devices/verify", summary="Record device verification metadata")
async def verify_device(
    payload: DeviceVerifyRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> dict:
    user = await _local_user(principal)
    try:
        return await matrix_encryption_service.verify_device(
            user_id=user["id"],
            device_id=payload.device_id,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Device not found"
        ) from exc


@router.post("/key-backup/init", summary="Record key backup initiation")
async def key_backup_init(
    payload: KeyBackupInitRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> dict:
    user = await _local_user(principal)
    return await matrix_encryption_service.init_key_backup(
        user_id=user["id"],
        backup_version=payload.backup_version,
        algorithm=payload.algorithm,
    )


@router.post("/key-backup/restore", summary="Audit key backup restore")
async def key_backup_restore(
    payload: KeyBackupInitRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> dict:
    user = await _local_user(principal)
    backups = await matrix_encryption_service.list_key_backups(user["id"])
    match = next((b for b in backups if b.get("backup_version") == payload.backup_version), None)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Backup version not found"
        )
    return match


@router.post("/cross-signing/status", summary="Report cross-signing bootstrap status")
async def cross_signing_status(
    payload: CrossSigningStatusRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> dict:
    user = await _local_user(principal)
    status_payload = await matrix_encryption_service.cross_signing_status(user["id"])
    status_payload["bootstrapped"] = payload.bootstrapped
    return status_payload


async def _room_settings_for_connection(connection_id: str, user_id: str) -> dict:
    await _require_active_connection(connection_id, user_id)
    mapping = await PostgresConversationRepository().get_by_connection(connection_id)
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    result = await call_json_function(
        "fn_matrix_room_settings",
        2,
        {"room_id": mapping["room_id"]},
    )
    row = row_from_jsonb(result)
    if row is None:
        return {
            "room_id": mapping["room_id"],
            "pinned_event_ids": [],
            "muted": False,
            "retention_policy": None,
            "metadata": {},
            "updated_at": None,
        }
    return row


@router.get(
    "/rooms/{connection_id}/settings",
    response_model=RoomSettingsResponse,
    summary="Get room settings",
)
async def get_room_settings(
    connection_id: UUID,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> RoomSettingsResponse:
    user = await _local_user(principal)
    row = await _room_settings_for_connection(str(connection_id), user["id"])
    return RoomSettingsResponse(**row)


@router.patch(
    "/rooms/{connection_id}/settings",
    response_model=RoomSettingsResponse,
    summary="Update room settings",
)
async def patch_room_settings(
    connection_id: UUID,
    payload: RoomSettingsPatchRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> RoomSettingsResponse:
    user = await _local_user(principal)
    await _require_active_connection(str(connection_id), user["id"])
    mapping = await PostgresConversationRepository().get_by_connection(str(connection_id))
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    patch: dict = {"room_id": mapping["room_id"]}
    if payload.pinned_event_ids is not None:
        patch["pinned_event_ids"] = payload.pinned_event_ids
    if payload.muted is not None:
        patch["muted"] = payload.muted
    if payload.retention_policy is not None:
        patch["retention_policy"] = payload.retention_policy
    if payload.metadata is not None:
        patch["metadata"] = payload.metadata
    result = await call_json_function("fn_matrix_room_settings", 1, patch)
    row = row_from_jsonb(result)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Settings update failed"
        )
    return RoomSettingsResponse(**row)


@router.get("/search/messages", summary="Search messages")
async def search_messages(
    _: MessageSender,
    principal: CurrentPrincipal,
    q: str = Query(min_length=1),
    room_id: str | None = None,
) -> dict:
    user = await _local_user(principal)
    try:
        results = await matrix_search_service.search_messages(
            user=user,
            search_term=q,
            room_id=room_id,
        )
    except MatrixSessionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        "results": results,
        "search_scope": "server",
        "note": "Encrypted room bodies may require client-side timeline search.",
    }


@router.get("/search/rooms", summary="Search rooms")
async def search_rooms(
    _: MessageSender,
    principal: CurrentPrincipal,
    q: str = Query(min_length=1),
) -> dict:
    user = await _local_user(principal)
    results = await matrix_search_service.search_rooms(user=user, search_term=q)
    return {"results": results, "search_scope": "server"}


@router.get("/search/attachments", summary="Search attachments")
async def search_attachments(
    _: MessageSender,
    principal: CurrentPrincipal,
    room_id: str | None = None,
    mimetype: str | None = None,
) -> dict:
    await _local_user(principal)
    results = await matrix_search_service.search_attachments(room_id=room_id, mimetype=mimetype)
    return {"results": results}


@router.post(
    "/attachments/metadata",
    response_model=AttachmentMetadataResponse,
    summary="Record attachment metadata after upload",
)
async def record_attachment_metadata(
    payload: AttachmentMetadataRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> AttachmentMetadataResponse:
    user = await _local_user(principal)
    if not await matrix_rate_limiter.check_media_limit(user["id"]):
        MATRIX_MEDIA_FAILED_TOTAL.inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Media rate limit"
        )
    if payload.size_bytes:
        max_bytes = max(
            settings.matrix.image_max_bytes,
            settings.matrix.document_max_bytes,
            settings.matrix.video_max_bytes,
        )
        if payload.size_bytes > max_bytes:
            MATRIX_MEDIA_FAILED_TOTAL.inc()
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large"
            )
    row = await matrix_search_service.record_attachment_metadata(
        room_id=payload.room_id,
        event_id=payload.event_id,
        uploaded_by_user_id=user["id"],
        mimetype=payload.mimetype,
        size_bytes=payload.size_bytes,
        sha256=payload.sha256,
        thumbnail_event_id=payload.thumbnail_event_id,
    )
    MATRIX_MEDIA_UPLOAD_TOTAL.inc()
    return AttachmentMetadataResponse(**row)


@router.get(
    "/notifications/preferences",
    response_model=NotificationPreferencesResponse,
    summary="Get notification preferences",
)
async def get_notification_preferences(
    _: MessageSender,
    principal: CurrentPrincipal,
) -> NotificationPreferencesResponse:
    user = await _local_user(principal)
    row = await matrix_notification_service.get_preferences(user["id"])
    return NotificationPreferencesResponse(**row)


@router.patch(
    "/notifications/preferences",
    response_model=NotificationPreferencesResponse,
    summary="Update notification preferences",
)
async def patch_notification_preferences(
    payload: NotificationPreferencesPatchRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> NotificationPreferencesResponse:
    user = await _local_user(principal)
    data = payload.model_dump(exclude_unset=True)
    quiet_start = data.pop("quiet_hours_start", None)
    quiet_end = data.pop("quiet_hours_end", None)
    row = await matrix_notification_service.update_preferences(
        user["id"],
        quiet_hours_start=str(quiet_start) if quiet_start is not None else None,
        quiet_hours_end=str(quiet_end) if quiet_end is not None else None,
        **data,
    )
    return NotificationPreferencesResponse(**row)


@router.post("/rooms/{connection_id}/events", summary="Publish business timeline event")
async def publish_business_event(
    connection_id: UUID,
    payload: BusinessEventPublishRequest,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> dict:
    user = await _local_user(principal)
    await _require_active_connection(str(connection_id), user["id"])
    if not await matrix_rate_limiter.check_message_limit(user["id"]):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Message rate limit"
        )
    mapping = await PostgresConversationRepository().get_by_connection(str(connection_id))
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    event_type = (
        payload.event_type
        if payload.event_type.startswith("com.paripath.")
        else f"com.paripath.{payload.event_type}"
    )
    content = {"aggregate_id": payload.aggregate_id, **payload.payload}
    try:
        return await matrix_business_event_service.publish(
            user=user,
            room_id=mapping["room_id"],
            event_type=event_type,
            content=content,
            aggregate_id=payload.aggregate_id,
        )
    except MatrixSessionNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
