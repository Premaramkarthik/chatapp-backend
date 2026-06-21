"""Chat conversation API models."""

from __future__ import annotations

from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationMappingSummary(BaseModel):
    """Subset of conversation mapping fields for API responses."""

    id: UUID | None = None
    user_connection_id: UUID | None = None
    room_id: str | None = None
    room_alias: str | None = None
    room_type: str | None = None
    status: str | None = None
    business_context: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationResponse(BaseModel):
    """Conversation mapping for a connection."""

    id: UUID
    user_connection_id: UUID
    room_id: str
    room_alias: str | None = None
    room_type: str = "dm"
    status: str
    business_context: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None


class InboxPeer(BaseModel):
    """Other participant in a 1:1 connection."""

    user_id: UUID
    display_name: str
    email: str | None = None
    matrix_user_id: str | None = None


class InboxItem(BaseModel):
    """One inbox row: connection + optional mapping + peer."""

    connection_id: UUID
    connection_status: str
    connected_at: datetime | None = None
    peer: InboxPeer
    mapping: ConversationMappingSummary | None = None
    can_chat: bool


class InboxResponse(BaseModel):
    """Chat inbox for the current user."""

    items: list[InboxItem]


class MatrixSessionResponse(BaseModel):
    """Matrix client session for matrix-js-sdk."""

    enabled: bool = True
    homeserver_url: str | None = None
    sliding_sync_url: str | None = None
    access_token: str | None = None
    user_id: str | None = None
    matrix_user_id: str | None = None
    device_id: str | None = None
    expires_in: int | None = None
    expires_in_sec: int | None = None


class MatrixDeviceResponse(BaseModel):
    """Known Matrix device metadata."""

    id: UUID
    device_id: str
    device_label: str | None = None
    trust_level: str
    last_seen_at: datetime | None = None
    verified_at: datetime | None = None


class MatrixDevicesResponse(BaseModel):
    items: list[MatrixDeviceResponse]


class DeviceVerifyRequest(BaseModel):
    device_id: str
    target_device_id: str | None = None


class KeyBackupInitRequest(BaseModel):
    backup_version: str
    algorithm: str = "m.megolm_backup.v1"


class KeyBackupRestoreRequest(BaseModel):
    backup_version: str


class CrossSigningStatusRequest(BaseModel):
    bootstrapped: bool = True


class RoomSettingsPatchRequest(BaseModel):
    pinned_event_ids: list[str] | None = None
    muted: bool | None = None
    retention_policy: str | None = None
    metadata: dict | None = None


class RoomSettingsResponse(BaseModel):
    room_id: str
    pinned_event_ids: list[str] = Field(default_factory=list)
    muted: bool = False
    retention_policy: str | None = None
    metadata: dict = Field(default_factory=dict)
    updated_at: datetime | None = None


class SearchResponse(BaseModel):
    items: list[dict]
    search_scope: str
    next_cursor: str | None = None
    note: str | None = None


class AttachmentMetadataRequest(BaseModel):
    room_id: str
    event_id: str
    mimetype: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    thumbnail_event_id: str | None = None


class AttachmentMetadataResponse(BaseModel):
    id: UUID
    room_id: str
    event_id: str
    mimetype: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    thumbnail_event_id: str | None = None
    created_at: datetime


class NotificationPreferencesResponse(BaseModel):
    user_id: UUID
    mentions_enabled: bool = True
    invites_enabled: bool = True
    messages_enabled: bool = True
    business_events_enabled: bool = True
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None


class NotificationPreferencesPatchRequest(BaseModel):
    mentions_enabled: bool | None = None
    invites_enabled: bool | None = None
    messages_enabled: bool | None = None
    business_events_enabled: bool | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None


class BusinessEventPublishRequest(BaseModel):
    event_type: str
    aggregate_id: str | None = None
    payload: dict = Field(default_factory=dict)
