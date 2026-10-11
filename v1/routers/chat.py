"""Chat conversation routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from core.config.settings import settings
from domains.auth.models import AuthSession
from domains.chat.permissions import (
    InboxStatusFilter,
    assert_can_chat,
    enrich_inbox_row,
    enrich_mapping_row,
    is_provisioned_room_id,
    mapping_allows_chat,
)
from domains.matrix.encryption.service import matrix_encryption_service
from domains.matrix.events.service import matrix_business_event_service
from domains.matrix.moderation.rate_limit import matrix_rate_limiter
from domains.matrix.notifications.service import matrix_notification_service
from domains.matrix.rooms.service import MatrixRoomProvisionError, matrix_room_service
from domains.matrix.search.service import matrix_search_service
from domains.matrix.session.service import MatrixSessionNotReadyError, matrix_session_service
from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import row_from_jsonb
from infrastructure.database.repositories.conversations import PostgresConversationRepository
from infrastructure.database.repositories.matching import PostgresMatchingRepository
from infrastructure.database.repositories.users import PostgresUserRepository
from v1.dependencies.auth import get_current_auth_session, get_current_principal, require_capability
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
CurrentBffSession = Annotated[AuthSession, Depends(get_current_auth_session)]
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


def _mapping_response(
    row: dict,
    *,
    can_chat: bool | None = None,
    is_user_archived: bool = False,
) -> ConversationResponse:
    enriched = enrich_mapping_row(
        row,
        can_chat=can_chat,
        is_user_archived=is_user_archived,
    )
    return ConversationResponse(
        id=enriched["id"],
        user_connection_id=enriched["user_connection_id"],
        room_id=enriched["room_id"],
        room_alias=enriched.get("room_alias"),
        room_type=enriched.get("room_type", "dm"),
        status=enriched["status"],
        business_context=enriched.get("business_context"),
        created_at=enriched["created_at"],
        updated_at=enriched.get("updated_at"),
        can_chat=enriched["can_chat"],
        is_archived=enriched["is_archived"],
        can_archive=enriched["can_archive"],
        can_reopen=enriched["can_reopen"],
    )


def _inbox_item(row: dict) -> InboxItem:
    enriched = enrich_inbox_row(row)
    return InboxItem(
        connection_id=enriched["connection_id"],
        connection_status=enriched["connection_status"],
        connected_at=enriched.get("connected_at"),
        peer=InboxPeer(**enriched["peer"]),
        mapping=(
            ConversationMappingSummary(**enriched["mapping"]) if enriched.get("mapping") else None
        ),
        status=enriched["status"],
        can_chat=enriched["can_chat"],
        is_archived=enriched["is_archived"],
        can_archive=enriched["can_archive"],
        can_reopen=enriched["can_reopen"],
    )


@router.get("/inbox", response_model=InboxResponse, summary="List 1:1 chat-eligible connections")
async def chat_inbox(
    _: MessageSender,
    principal: CurrentPrincipal,
    status: Annotated[
        InboxStatusFilter,
        Query(description="Filter inbox by conversation mapping status"),
    ] = "active",
) -> InboxResponse:
    user = await _local_user(principal)
    rows = await PostgresConversationRepository().list_inbox(user["id"], inbox_status=status)
    return InboxResponse(items=[_inbox_item(row) for row in rows])


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
    connection = await _require_active_connection(str(connection_id), user["id"])
    repo = PostgresConversationRepository()
    mapping = await repo.get_by_connection(str(connection_id))
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    if not is_provisioned_room_id(mapping.get("room_id")):
        try:
            mapping = await matrix_room_service.provision_dm_for_connection(
                connection=connection,
                created_by_user_id=user["id"],
            )
        except MatrixRoomProvisionError:
            pass
    is_user_archived = await repo.is_user_archived(user["id"], str(connection_id))
    can_chat = mapping_allows_chat(mapping.get("status"), mapping.get("room_id"))
    return _mapping_response(
        mapping,
        can_chat=can_chat,
        is_user_archived=is_user_archived,
    )


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
            user_id=user["id"],
            reason="user_archive",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found"
        ) from exc
    return _mapping_response(
        mapping,
        can_chat=mapping_allows_chat(mapping.get("status"), mapping.get("room_id")),
        is_user_archived=True,
    )


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
        mapping = await matrix_room_service.reopen_for_connection(
            connection_id=str(connection_id),
            user_id=user["id"],
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found"
        ) from exc
    can_chat = mapping_allows_chat(mapping.get("status"), mapping.get("room_id"))
    return _mapping_response(mapping, can_chat=can_chat, is_user_archived=False)


@router.post("/matrix/signin/start", summary="Start device-bound Synapse SSO")
async def start_matrix_signin(
    bff_session: CurrentBffSession, _: MessageSender, principal: CurrentPrincipal
) -> dict:
    user = await _local_user(principal)
    try:
        return await matrix_session_service.start_login(user=user, bff_session_id=bff_session.id)
    except MatrixSessionNotReadyError as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc


@router.get("/matrix/callback", summary="Complete single-use Matrix SSO")
async def matrix_callback(
    bff_session: CurrentBffSession,
    _: MessageSender,
    principal: CurrentPrincipal,
    state: str = Query(min_length=20, max_length=256),
    loginToken: str = Query(min_length=1, max_length=4096),
) -> RedirectResponse:
    from domains.matrix.session.service import validate_matrix_urls

    validate_matrix_urls()
    try:
        await matrix_session_service.complete_login(
            state=state, login_token=loginToken, bff_session_id=bff_session.id
        )
    except MatrixSessionNotReadyError as exc:
        raise HTTPException(409, detail={"code": "matrix_login_required"}) from exc
    return RedirectResponse(
        settings.matrix.post_login_url,
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get(
    "/matrix/session", response_model=MatrixSessionResponse, summary="Get Matrix client session"
)
async def get_matrix_session(
    request: Request,
    bff_session: CurrentBffSession,
    response: Response,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> MatrixSessionResponse:
    user = await _local_user(principal)
    try:
        session = await matrix_session_service.create_session(
            user=user,
            bff_session_id=bff_session.id,
            request_id=request_id_from(request),
        )
    except MatrixSessionNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "matrix_login_required"}
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return MatrixSessionResponse(enabled=True, **session)


@router.post(
    "/matrix/session", response_model=MatrixSessionResponse, summary="Create Matrix session"
)
async def create_matrix_session(
    request: Request,
    bff_session: CurrentBffSession,
    response: Response,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> MatrixSessionResponse:
    return await get_matrix_session(request, bff_session, response, _, principal)


@router.post(
    "/matrix/session/refresh",
    response_model=MatrixSessionResponse,
    summary="Refresh Matrix session",
)
async def refresh_matrix_session(
    request: Request,
    bff_session: CurrentBffSession,
    response: Response,
    _: MessageSender,
    principal: CurrentPrincipal,
) -> MatrixSessionResponse:
    user = await _local_user(principal)
    try:
        session = await matrix_session_service.refresh_session(
            user=user,
            bff_session_id=bff_session.id,
            request_id=request_id_from(request),
        )
    except MatrixSessionNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "matrix_login_required"}
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return MatrixSessionResponse(enabled=True, **session)


@router.post("/matrix/rooms/membership", summary="Reconcile joined Matrix membership")
async def reconcile_room_membership(
    request: Request,
    bff_session: CurrentBffSession,
    _: MessageSender,
    principal: CurrentPrincipal,
    room_id: str = Query(min_length=3, max_length=512),
) -> dict:
    from urllib.parse import quote

    import httpx

    from domains.matrix.authorization import require_room_access
    from infrastructure.database.connection import execute, fetchrow

    user = await _local_user(principal)
    await require_room_access(str(user["id"]), room_id)
    credentials = await matrix_session_service.create_session(
        user=user, bff_session_id=bff_session.id
    )
    try:
        async with httpx.AsyncClient(timeout=settings.http.timeout_seconds) as http:
            response = await http.get(
                f'{settings.matrix.homeserver_url.rstrip("/")}/_matrix/client/v3/rooms/{quote(room_id,safe="")}/joined_members',
                headers={"Authorization": "Bearer " + credentials["access_token"]},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(503, detail={"code": "matrix_membership_unavailable"}) from exc
    if response.status_code != 200:
        raise HTTPException(503, detail={"code": "matrix_membership_unavailable"})
    expected = await fetchrow(
        """SELECT a.mxid AS a,b.mxid AS b FROM matrix_room_mappings m
      JOIN user_connections c ON c.id=m.user_connection_id
      JOIN matrix_user_mappings a ON a.user_id=c.user_a_id
      JOIN matrix_user_mappings b ON b.user_id=c.user_b_id WHERE m.room_id=$1""",
        room_id,
    )
    joined = bool(
        expected and set(response.json().get("joined", {})) == {expected["a"], expected["b"]}
    )
    if joined:
        await execute(
            """UPDATE matrix_room_mappings SET status='joined',updated_at=now()
            WHERE room_id=$1 AND status IN ('invited','joined','active')""",
            room_id,
        )
    return {"status": "joined" if joined else "invited"}


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
    raise HTTPException(410, detail={"code": "matrix_client_search_required"})


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
    user = await _local_user(principal)
    results = await matrix_search_service.search_attachments(
        user_id=str(user["id"]), room_id=room_id, mimetype=mimetype
    )
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
    can_chat = mapping_allows_chat(mapping.get("status"), mapping.get("room_id"))
    perms = enrich_mapping_row(mapping, can_chat=can_chat)
    try:
        assert_can_chat(perms)
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "matrix_room_access_denied"}) from exc
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "matrix_login_required"}
        ) from exc
