# Matrix Chat Platform — End-to-End Guide

This document describes the complete **Matrix/Synapse chat integration** for PariPath: architecture, database schema, provisioning flows, HTTP API, E2E encryption, Docker stack, frontend integration, observability, and operational runbooks.

**Design principle:** Message bodies and cryptographic keys stay on **Synapse** and in the **browser** (matrix-js-sdk + Rust crypto). The BFF stores **mappings and metadata only** — no message content in PostgreSQL.

**Source code roots:**

| Area | Path |
|------|------|
| Matrix infrastructure | [`infrastructure/matrix/`](../infrastructure/matrix/) |
| Domain services | [`domains/matrix/`](../domains/matrix/) |
| HTTP API | [`v1/routers/chat.py`](../v1/routers/chat.py) |
| Schemas | [`v1/schemas/chat.py`](../v1/schemas/chat.py) |
| Migrations | [`migrations/007_matrix_chat.sql`](../migrations/007_matrix_chat.sql), [`migrations/008_matrix_functions.sql`](../migrations/008_matrix_functions.sql) |
| Synapse config | [`docker/synapse/homeserver.yaml`](../docker/synapse/homeserver.yaml) |
| Frontend | [`connect-carry/src/app/chat/`](../../connect-carry/src/app/chat/), [`connect-carry/docs/matrix-chat.md`](../../connect-carry/docs/matrix-chat.md) |

---

## Overview

PariPath chat replaces the legacy Tinode stack with:

| Component | Role |
|-----------|------|
| **Synapse** | Matrix homeserver — users, rooms, E2EE, media, server-side message search |
| **Sliding Sync (MSC3575)** | Efficient client sync via `sliding-sync` proxy |
| **FastAPI BFF** | Keycloak auth, user provisioning, room mapping, metadata, rate limits |
| **PostgreSQL** | User/room mappings, device trust metadata, attachment index — **no message bodies** |
| **Redis** | Matrix session token cache + BFF rate limit counters |
| **matrix-js-sdk** (browser) | E2EE, Sliding Sync, IndexedDB crypto store, offline queue |

```mermaid
flowchart TB
  subgraph browser [connect-carry browser]
    ChatPage[ChatPage]
    MP[MatrixProvider]
    SDK[matrix-js-sdk + Rust crypto]
    IDB[(IndexedDB keys)]
  end

  subgraph bff [FastAPI BFF]
    ChatRouter["/v1/chat"]
    Prov[ProvisioningService]
    Session[SessionService]
    Rooms[RoomService]
    Mod[ModerationService]
  end

  subgraph matrix [Matrix stack]
    SS[Sliding Sync :8090]
    Syn[Synapse :8008]
    SynDB[(synapse-db)]
    SyncDB[(syncv3 DB)]
  end

  subgraph pg [PostgreSQL app DB]
    MUM[matrix_user_mappings]
    MRM[matrix_room_mappings]
    Meta[devices attachments settings]
  end

  subgraph redis [Redis]
    MSC["matrix:session:{user_id}"]
    RL["matrix:rate:*"]
  end

  ChatPage --> MP --> SDK
  SDK -->|Sliding Sync| SS
  SDK -->|E2EE messages media| Syn
  MP --> ChatRouter
  ChatRouter --> Prov --> Syn
  ChatRouter --> Session --> MSC
  ChatRouter --> Rooms --> Syn
  Prov --> MUM
  Rooms --> MRM
  ChatRouter --> Meta
  Syn --> SynDB
  SS --> SyncDB
  SS --> Syn
  Mod --> RL
```

---

## Entity-Relationship Diagram (PostgreSQL)

All Matrix tables are defined in [`migrations/007_matrix_chat.sql`](../migrations/007_matrix_chat.sql). PL/pgSQL access functions are in [`migrations/008_matrix_functions.sql`](../migrations/008_matrix_functions.sql).

```mermaid
erDiagram
    users ||--o| matrix_user_mappings : "1:1 Matrix identity"
    users ||--o{ matrix_user_devices : owns
    users ||--o| matrix_notification_preferences : has
    users ||--o{ matrix_key_backup_metadata : records
    users ||--o{ matrix_attachment_metadata : uploads
    users ||--o{ matrix_room_archives : archives

    user_connections ||--o| matrix_room_mappings : "1:1 DM room"
    users ||--o{ matrix_room_mappings : "created_by"

    matrix_room_mappings ||--o| matrix_room_settings : settings
    matrix_room_mappings ||--o{ matrix_business_events : events
    matrix_room_mappings ||--o{ matrix_attachment_metadata : attachments
    matrix_room_mappings ||--o{ matrix_room_archives : archives

    reports ||--o| matrix_reports : "chat context"

    users {
        uuid id PK
        text keycloak_sub
        text display_name
        text email
        text account_mode
        text status
    }

    user_connections {
        uuid id PK
        uuid user_a_id FK
        uuid user_b_id FK
        text status
        timestamptz connected_at
    }

    matrix_user_mappings {
        uuid id PK
        uuid user_id FK UK
        text mxid UK
        text localpart UK
        text password_encrypted
        text provision_status
        timestamptz created_at
        timestamptz updated_at
    }

    matrix_room_mappings {
        uuid id PK
        uuid user_connection_id FK UK
        text room_id UK
        text room_alias
        text room_type
        text status
        jsonb business_context
        uuid created_by_user_id FK
        timestamptz created_at
        timestamptz updated_at
    }

    matrix_user_devices {
        uuid id PK
        uuid user_id FK
        text device_id
        text device_label
        text trust_level
        timestamptz last_seen_at
        timestamptz verified_at
    }

    matrix_key_backup_metadata {
        uuid id PK
        uuid user_id FK
        text backup_version
        text algorithm
        timestamptz created_at
    }

    matrix_notification_preferences {
        uuid user_id PK FK
        bool mentions_enabled
        bool invites_enabled
        bool messages_enabled
        bool business_events_enabled
        time quiet_hours_start
        time quiet_hours_end
    }

    matrix_attachment_metadata {
        uuid id PK
        text room_id
        text event_id
        text mimetype
        bigint size_bytes
        text sha256
        text thumbnail_event_id
        uuid uploaded_by_user_id FK
        timestamptz created_at
    }

    matrix_business_events {
        uuid id PK
        text room_id
        text event_id
        text event_type
        text aggregate_id
        text payload_hash
        timestamptz published_at
    }

    matrix_room_settings {
        text room_id PK
        jsonb pinned_event_ids
        bool muted
        text retention_policy
        jsonb metadata
        timestamptz updated_at
    }

    matrix_room_archives {
        uuid id PK
        text room_id
        uuid archived_by_user_id FK
        text reason
        timestamptz archived_at
    }

    matrix_reports {
        uuid id PK
        uuid report_id FK
        text room_id
        text event_id
        timestamptz created_at
    }
```

### Table purposes

| Table | Stores | Does NOT store |
|-------|--------|----------------|
| `matrix_user_mappings` | MXID, encrypted Synapse password, provision status | Access tokens (Redis cache only) |
| `matrix_room_mappings` | Connection ↔ room_id, status, business context | Message events |
| `matrix_user_devices` | Device trust metadata for BFF UI | Crypto keys |
| `matrix_key_backup_metadata` | Backup version audit trail | Key backup payload |
| `matrix_attachment_metadata` | MXC event references, mimetype, size, sha256 | File bytes (Synapse media repo) |
| `matrix_business_events` | Custom timeline event audit (`com.paripath.*`) | Full event JSON (on Synapse) |
| `matrix_room_settings` | Pins, mute, retention policy | — |
| `matrix_room_archives` | Archive audit log | — |
| `matrix_reports` | Links user reports to room/event context | — |

### Room status lifecycle

```mermaid
stateDiagram-v2
    [*] --> provisioning: connection accepted
    provisioning --> active: Synapse room created
    provisioning --> failed: provision error
    active --> archived: block or manual archive
    archived --> active: reopen
```

Placeholder room_id before provision: `!pending_{connection_id}:local`

---

## SQL Functions

All Matrix DB access goes through PL/pgSQL functions (no raw table writes from Python).

| Function | Modes | Purpose |
|----------|-------|---------|
| `fn_matrix_user_mappings` | 1=upsert, 2=by user_id, 3=by keycloak_sub, 4=by mxid | User ↔ MXID mapping |
| `fn_matrix_room_mappings` | 1=get, 2=provision, 3=inbox, 4=update, 5=archive, 6=reopen | Room lifecycle |
| `fn_matrix_user_devices` | 1=upsert, 2=list, 3=get, 4=delete, 5=verify | Device metadata |
| `fn_matrix_attachment_metadata` | 1=upsert, 2=list by room, 3=search | Attachment index |
| `fn_matrix_business_events` | 1=record, 2=list by room | Business event audit |
| `fn_matrix_notification_preferences` | 1=patch, 2=get-or-create | Notification prefs |
| `fn_matrix_key_backup_metadata` | 1=upsert, 2=list | Key backup audit |
| `fn_matrix_room_settings` | 1=patch, 2=get | Room settings |
| `fn_matrix_reports` | 1=insert | Report ↔ room link |

Repositories: [`infrastructure/database/repositories/matrix_*.py`](../infrastructure/database/repositories/)

---

## User Provisioning Flow

Matrix users are **never self-registered**. Synapse has `enable_registration: false`. All users are created via the **Synapse Admin API**.

```mermaid
sequenceDiagram
    participant KC as Keycloak
    participant BFF as FastAPI BFF
    participant Admin as SynapseAdminClient
    participant Syn as Synapse
    participant PG as PostgreSQL

    Note over KC,PG: On first bootstrap / session request
    KC->>BFF: JWT (keycloak_sub)
    BFF->>PG: fn_users — resolve local user_id
    alt no matrix_user_mappings row
        BFF->>BFF: localpart = u{uuid-no-dashes}
        BFF->>BFF: mxid = @localpart:matrix.local
        BFF->>BFF: generate random password
        BFF->>Admin: PUT /_synapse/admin/v2/users/{mxid}
        Admin->>Syn: create/update user
        BFF->>PG: fn_matrix_user_mappings upsert (password_encrypted)
    end

    Note over BFF,Syn: Session issuance
    BFF->>Admin: POST /_synapse/admin/v1/users/{mxid}/login
    Admin->>Syn: issue access token
    BFF->>BFF: cache in Redis matrix:session:{user_id}
    BFF-->>BFF: return token + homeserver + sliding_sync URLs
```

### MXID format

```text
@u{user_id_without_hyphens}:{MATRIX_SERVER_NAME}
```

Example: `@u550e8400e29b41d4a716446655440000:matrix.local`

### Password handling

- Random 32-byte URL-safe secret generated at provision time
- Encrypted with `TokenCipher` → stored in `password_encrypted`
- **Never sent to the client** — session uses short-lived admin-issued login tokens

### Bootstrap entry points

| Trigger | Code |
|---------|------|
| User bootstrap on sign-in | [`domains/users/bootstrap.py`](../domains/users/bootstrap.py) |
| Session request (lazy re-provision) | [`domains/matrix/session/service.py`](../domains/matrix/session/service.py) |
| Connection accept (room provision) | [`domains/matrix/rooms/service.py`](../domains/matrix/rooms/service.py) via [`v1/routers/connections.py`](../v1/routers/connections.py) |

---

## Room Provisioning Flow (E2EE DM)

When a connection is **accepted**, the BFF auto-provisions an encrypted 1:1 Matrix room.

```mermaid
sequenceDiagram
    participant Conn as connections API
    participant Rooms as matrix_room_service
    participant PG as PostgreSQL
    participant Admin as SynapseAdminClient
    participant Syn as Synapse

    Conn->>Rooms: maybe_auto_provision_on_accept(connection_id)
    Rooms->>PG: fn_matrix_room_mappings mode=2 (status=provisioning)
    Rooms->>Admin: create_login_token(creator)
    Rooms->>Syn: createRoom (trusted_private_chat, is_direct=true)
    Note over Syn: Initial state m.room.encryption = m.megolm.v1.aes-sha2
    Rooms->>Syn: invite peer MXID
    Rooms->>PG: update room_id, status=active
```

Room creation: [`infrastructure/matrix/client.py`](../infrastructure/matrix/client.py) → `create_direct_encrypted_room()`

**Moderation hooks:**

- User blocked → [`domains/matrix/moderation/service.py`](../domains/matrix/moderation/service.py) archives DM
- User reported → links room/event to `matrix_reports`

---

## Session Management

### Redis cache ([`infrastructure/matrix/session_cache.py`](../infrastructure/matrix/session_cache.py))

| Key | Value | TTL |
|-----|-------|-----|
| `matrix:session:{user_id}` | `{ access_token, device_id, mxid, expires_in }` | `min(expires_in, MATRIX_SESSION_CACHE_TTL_SEC)` default 300s |

Invalidated on `POST /v1/chat/matrix/session/refresh`.

### Session response shape

```json
{
  "enabled": true,
  "homeserver_url": "http://localhost:8008",
  "sliding_sync_url": "http://localhost:8090",
  "access_token": "...",
  "user_id": "local-uuid",
  "matrix_user_id": "@u...:matrix.local",
  "device_id": "...",
  "expires_in": 3600,
  "expires_in_sec": 3600
}
```

Browser uses `MATRIX_PUBLIC_HOMESERVER_URL` when set (falls back to `MATRIX_HOMESERVER_URL`).

---

## HTTP API Reference

**Router prefix:** `/v1/chat`  
**Auth:** All endpoints require session cookie or Bearer JWT + capability **`message:send`**.

### Inbox & conversations

| Method | Path | Summary | Response |
|--------|------|---------|----------|
| GET | `/v1/chat/inbox` | Active connections eligible for chat | `InboxResponse { items: InboxItem[] }` |
| GET | `/v1/chat/conversations/{connection_id}` | Room mapping for connection | `ConversationResponse` |
| POST | `/v1/chat/conversations/{connection_id}/archive` | Archive DM | `ConversationResponse` |
| POST | `/v1/chat/conversations/{connection_id}/reopen` | Reopen archived DM | `ConversationResponse` |

**`InboxItem` fields:** `connection_id`, `connection_status`, `connected_at`, `peer { user_id, display_name, email, matrix_user_id }`, `mapping?`, `can_chat`

### Matrix session

| Method | Path | Summary |
|--------|------|---------|
| GET | `/v1/chat/matrix/session` | Get or create session (cached) |
| POST | `/v1/chat/matrix/session` | Alias for GET |
| POST | `/v1/chat/matrix/session/refresh` | Invalidate cache, re-issue token |

Returns **409** if Matrix user not provisioned and re-provision fails.

### Devices & encryption metadata

| Method | Path | Summary |
|--------|------|---------|
| GET | `/v1/chat/devices` | List device metadata from Postgres |
| DELETE | `/v1/chat/devices/{device_id}` | Remove local device metadata (204) |
| POST | `/v1/chat/devices/verify` | Record SAS verification `{ device_id, target_device_id? }` |
| POST | `/v1/chat/key-backup/init` | Record backup initiation `{ backup_version, algorithm? }` |
| POST | `/v1/chat/key-backup/restore` | Audit restore attempt |
| POST | `/v1/chat/cross-signing/status` | Report cross-signing bootstrap `{ bootstrapped: bool }` |

**Important:** Key material never transits the BFF. These endpoints are **audit/metadata only**.

### Room settings

| Method | Path | Summary |
|--------|------|---------|
| GET | `/v1/chat/rooms/{connection_id}/settings` | Pins, mute, retention, metadata |
| PATCH | `/v1/chat/rooms/{connection_id}/settings` | Partial update |

### Search (message search stays on Synapse)

| Method | Path | Query | Scope |
|--------|------|-------|-------|
| GET | `/v1/chat/search/messages` | `q`, `room_id?` | Synapse server search proxy |
| GET | `/v1/chat/search/rooms` | `q` | Inbox substring match (BFF) |
| GET | `/v1/chat/search/attachments` | `room_id?`, `mimetype?` | Local `matrix_attachment_metadata` only |

### Attachments & notifications

| Method | Path | Summary |
|--------|------|---------|
| POST | `/v1/chat/attachments/metadata` | Record post-upload metadata (rate + size limited) |
| GET | `/v1/chat/notifications/preferences` | Get notification prefs |
| PATCH | `/v1/chat/notifications/preferences` | Patch notification prefs |

### Business events

| Method | Path | Summary |
|--------|------|---------|
| POST | `/v1/chat/rooms/{connection_id}/events` | Publish `com.paripath.{event_type}` custom event |

**Request:** `{ event_type, aggregate_id?, payload: {} }`  
Rate limited (message rate limit bucket).

---

## E2E Encryption

### Server-side (room creation)

Every provisioned DM room includes initial state:

```json
{
  "type": "m.room.encryption",
  "content": { "algorithm": "m.megolm.v1.aes-sha2" }
}
```

Synapse config: `encryption_enabled_by_default_for_room_type: invite`

### Client-side (connect-carry)

| Concern | Implementation |
|---------|----------------|
| Crypto engine | `client.initRustCrypto({ useIndexedDB, storageKey })` |
| Sliding Sync | `SlidingSync` with DM list + per-room subscriptions |
| Cross-signing | `MatrixProvider.bootstrapEncryption()` |
| Key backup | `checkKeyBackupAndEnable()` / restore with passphrase |
| Device verification | SAS via `VerificationModal` (matrix-js-sdk) |
| Offline queue | IndexedDB `matrix-offline-queue` |
| UI | `EncryptionHealthBanner`, `VerifiedDeviceBadge`, `DeviceManagementModal` |

### Data flow for encrypted messages

```mermaid
sequenceDiagram
    participant User
    participant Composer as MessageComposer
    participant SDK as matrix-js-sdk
    participant SS as Sliding Sync
    participant Syn as Synapse

    User->>Composer: type message
    Composer->>SDK: sendMessage (Megolm encrypt)
    SDK->>Syn: PUT /rooms/{roomId}/send/m.room.message
    Syn-->>SS: new event
    SS-->>SDK: sync to peer client
    SDK->>SDK: decrypt with session keys (IndexedDB)
```

The BFF is **not** in the message path for normal chat — only for session bootstrap and metadata.

---

## Media & Attachments

### Synapse media repo

- Uploads go **directly** from browser → Synapse (`max_upload_size: 100M`)
- Stored at `media_store_path: /data/media_store` (Docker volume `synapse_data`)

### BFF size gates (metadata recording only)

| Type | Env var | Default |
|------|---------|---------|
| Image | `MATRIX_IMAGE_MAX_BYTES` | 10 MB |
| Document | `MATRIX_DOCUMENT_MAX_BYTES` | 25 MB |
| Video | `MATRIX_VIDEO_MAX_BYTES` | 100 MB |

### Attachment flow (intended)

```mermaid
sequenceDiagram
    participant Client
    participant Syn as Synapse media API
    participant BFF as POST /attachments/metadata
    participant PG as matrix_attachment_metadata

    Client->>Syn: upload encrypted media (MXC URL)
    Client->>BFF: { room_id, event_id, mimetype, size_bytes, sha256 }
    BFF->>BFF: rate limit + size check
    BFF->>PG: fn_matrix_attachment_metadata upsert
```

**Frontend status:** `MessageComposer` attachment button shows a stub toast — upload + metadata recording not fully wired yet.

---

## Rate Limiting

Implementation: [`domains/matrix/moderation/rate_limit.py`](../domains/matrix/moderation/rate_limit.py) — Redis increment with TTL window.

| Limit | Redis key | Default | Applied to |
|-------|-----------|---------|------------|
| Messages / events | `matrix:rate:message:{user_id}` | 60 / 60s | `POST /rooms/{connection_id}/events` |
| Media metadata | `matrix:rate:media:{user_id}` | 20 / 60s | `POST /attachments/metadata` |

Exceeded → HTTP **429**.

**Synapse-side** (separate from BFF): `rc_message` 10/s, burst 50 in `homeserver.yaml`.

---

## Docker Stack

From [`docker-compose.yml`](../docker-compose.yml):

### Service topology

```mermaid
flowchart LR
  subgraph compose [docker-compose]
    SDB[synapse-db :5432]
    Syn[synapse :8008 / :9001 metrics]
    SS[sliding-sync :8090]
    Redis[redis :6379]
  end

  Syn --> SDB
  Syn --> Redis
  SS --> Syn
  SS --> SDB
```

### `synapse-db`

```yaml
image: postgres:17-alpine
POSTGRES_USER/PASSWORD/DB: synapse/synapse/synapse
volumes: synapse_db_data
init: docker/postgres/init-syncv3-db.sh  # creates syncv3 database
```

### `synapse`

```yaml
image: matrixdotorg/synapse:latest
ports:
  - "${SYNAPSE_HOST_PORT:-8008}:8008"
  - "${SYNAPSE_METRICS_PORT:-9001}:9000"
volumes:
  - ./docker/synapse/homeserver.yaml:/data/homeserver.yaml:ro
  - ./docker/synapse/log.config:/data/log.config:ro
  - synapse_data:/data
depends_on: synapse-db (healthy), redis (healthy)
healthcheck: curl http://127.0.0.1:8008/health
```

### `sliding-sync`

```yaml
image: ghcr.io/matrix-org/sliding-sync:latest
ports: "${SLIDING_SYNC_HOST_PORT:-8090}:8090"
environment:
  SYNCV3_SERVER: http://synapse:8008
  SYNCV3_DB: postgres://synapse:synapse@synapse-db:5432/syncv3?sslmode=disable
  SYNCV3_SECRET: ${SLIDING_SYNC_SECRET}
depends_on: synapse (healthy), synapse-db (healthy)
healthcheck: POST /_matrix/client/unstable/org.matrix.msc3575/sync → expect 401
```

### Synapse configuration highlights

File: [`docker/synapse/homeserver.yaml`](../docker/synapse/homeserver.yaml)

| Setting | Value | Notes |
|---------|-------|-------|
| `server_name` | `matrix.local` | MXID domain |
| `enable_registration` | `false` | Admin API only |
| `registration_shared_secret` | env-matched | Dev provisioning |
| `encryption_enabled_by_default_for_room_type` | `invite` | E2EE on invite rooms |
| `max_upload_size` | `100M` | Media limit |
| `search.enabled` | `true` | Server-side message search |
| `enable_admin_api` | `true` | Required for BFF provisioning |
| `redis.enabled` | `true` | Synapse internal cache |

---

## Environment Variables

From [`core/config/settings.py`](../core/config/settings.py) (`MatrixSettings`) and [`.env.example`](../.env.example):

| Variable | Default | Purpose |
|----------|---------|---------|
| `MATRIX_ENABLED` | `true` | Master switch |
| `MATRIX_HOMESERVER_URL` | `http://localhost:8008` | BFF → Synapse (internal) |
| `MATRIX_PUBLIC_HOMESERVER_URL` | `""` | Browser-facing URL (falls back to homeserver URL) |
| `MATRIX_SLIDING_SYNC_URL` | `http://localhost:8090` | Sliding Sync proxy |
| `MATRIX_SERVER_NAME` | `matrix.local` | MXID domain suffix |
| `MATRIX_ADMIN_TOKEN` | `""` | Synapse admin API bearer token |
| `MATRIX_ACCESS_TOKEN_TTL_SEC` | `3600` | Login token validity |
| `MATRIX_SESSION_CACHE_TTL_SEC` | `300` | Redis session cache cap |
| `MATRIX_REGISTRATION_SHARED_SECRET` | dev secret | Must match Synapse config |
| `MATRIX_IMAGE_MAX_BYTES` | 10485760 | Metadata size gate |
| `MATRIX_DOCUMENT_MAX_BYTES` | 26214400 | |
| `MATRIX_VIDEO_MAX_BYTES` | 104857600 | |
| `MATRIX_MESSAGE_RATE_LIMIT` | 60 | BFF message/event limit per window |
| `MATRIX_MESSAGE_RATE_WINDOW_SEC` | `60` | |
| `MATRIX_MEDIA_RATE_LIMIT` | 20 | BFF media metadata limit |
| `MATRIX_MEDIA_RATE_WINDOW_SEC` | 60 | |
| `SYNAPSE_HOST_PORT` | 8008 | Docker port mapping |
| `SYNAPSE_METRICS_PORT` | 9001 | Prometheus scrape port |
| `SLIDING_SYNC_HOST_PORT` | 8090 | |
| `SLIDING_SYNC_SECRET` | dev secret | Sliding sync proxy auth |

Also requires `AUTH_TOKEN_ENCRYPTION_KEY` for encrypting Synapse passwords at rest.

---

## Health Checks & Observability

### Readiness ([`v1/routers/health.py`](../v1/routers/health.py))

When `MATRIX_ENABLED=true`:

| Check | Probe | OK when |
|-------|-------|---------|
| `matrix` | `GET {MATRIX_HOMESERVER_URL}/_matrix/client/versions` | HTTP 200 |
| `sliding_sync` | `POST {SLIDING_SYNC_URL}/.../msc3575/sync` | 401/403/405 (auth required = alive) |

When disabled: both return `{ ok: true, detail: "disabled" }`.

Implementation: [`infrastructure/matrix/health.py`](../infrastructure/matrix/health.py)

### Prometheus metrics

From [`core/observability/prometheus_metrics.py`](../core/observability/prometheus_metrics.py):

| Metric | Labels |
|--------|--------|
| `matrix_admin_requests_total` | `method`, `outcome` |
| `matrix_admin_duration_seconds` | `method` |
| `matrix_media_upload_total` | — |
| `matrix_media_failed_total` | — |
| `matrix_session_cache_hits_total` | — |
| `matrix_session_cache_misses_total` | — |

Grafana dashboard: [`docker/observability/grafana/dashboards/matrix.json`](../docker/observability/grafana/dashboards/matrix.json)

Log categories: [`core/logging/matrix_categories.py`](../core/logging/matrix_categories.py)

---

## Frontend Integration (connect-carry)

### File map

```
src/routes/_app/chat.tsx              # Route wrapper with MatrixProvider
src/lib/api/chat.ts                   # BFF client for all /v1/chat endpoints
src/app/chat/
├── lib/matrix-client.ts              # matrix-js-sdk + SlidingSync + crypto
├── providers/MatrixProvider.tsx      # Session bootstrap, sync state, send API
├── pages/ChatPage.tsx                # Inbox + live timeline split view
└── components/
    ├── MessageTimeline.tsx
    ├── MessageComposer.tsx
    ├── EncryptionHealthBanner.tsx
    ├── SessionManager.tsx
    ├── DeviceManagementModal.tsx
    ├── VerificationModal.tsx
    ├── RoomSearchPanel.tsx
    ├── PinnedMessagesPanel.tsx
    ├── NotificationSettingsModal.tsx
    ├── BlockedUsersModal.tsx
    └── BusinessEventCard.tsx
```

See also: [`connect-carry/docs/matrix-chat.md`](../../connect-carry/docs/matrix-chat.md)

### Client bootstrap sequence

```mermaid
sequenceDiagram
    participant Page as ChatPage
    participant MP as MatrixProvider
    participant BFF as chatApi
    participant SDK as matrix-js-sdk

    Page->>MP: mount
    MP->>BFF: GET /v1/chat/matrix/session
    BFF-->>MP: access_token, homeserver, sliding_sync_url
    MP->>SDK: createClient + initRustCrypto
    MP->>SDK: startClient({ slidingSync })
    MP->>BFF: GET /v1/chat/inbox
    BFF-->>MP: connections + room_ids
    MP->>SDK: subscribeRoom(selected connection)
    SDK-->>Page: encrypted timeline events
```

### BFF client methods ([`src/lib/api/chat.ts`](../../connect-carry/src/lib/api/chat.ts))

| Method | HTTP |
|--------|------|
| `getInbox()` | GET `/v1/chat/inbox` |
| `getConversation(connectionId)` | GET `/v1/chat/conversations/{id}` |
| `getMatrixSession()` | GET `/v1/chat/matrix/session` |
| `refreshMatrixSession()` | POST `/v1/chat/matrix/session/refresh` |
| `listDevices()` | GET `/v1/chat/devices` |
| `deleteDevice(deviceId)` | DELETE `/v1/chat/devices/{id}` |
| `getRoomSettings(connectionId)` | GET `/v1/chat/rooms/{id}/settings` |
| `patchRoomSettings(...)` | PATCH `/v1/chat/rooms/{id}/settings` |
| `searchMessages(q, roomId?)` | GET `/v1/chat/search/messages` |
| `searchAttachments(...)` | GET `/v1/chat/search/attachments` |
| `recordAttachmentMetadata(...)` | POST `/v1/chat/attachments/metadata` |
| `getNotificationPreferences()` | GET `/v1/chat/notifications/preferences` |
| `patchNotificationPreferences(...)` | PATCH `/v1/chat/notifications/preferences` |
| `publishBusinessEvent(...)` | POST `/v1/chat/rooms/{id}/events` |

### Frontend gaps (partial implementation)

| Feature | Status |
|---------|--------|
| Live E2EE messaging | Implemented |
| Sliding Sync | Implemented |
| Device verification UI | Implemented (SAS via SDK) |
| BFF `POST /devices/verify` after SAS | Not always called post-verification |
| Media upload + metadata | Stub toast only |
| Business event publishing | API exists; UI not wired |
| `refreshMatrixSession()` | API exists; SessionManager uses retry bootstrap |

---

## Backend File Map

```
infrastructure/matrix/
├── admin.py           # SynapseAdminClient (create user, login token, deactivate)
├── client.py          # create_direct_encrypted_room, send custom events, search proxy
├── session_cache.py   # Redis matrix:session:{user_id}
├── health.py          # Synapse + sliding sync probes
└── __init__.py

domains/matrix/
├── provisioning/service.py   # Keycloak user → Synapse account
├── session/service.py        # Token issuance + cache
├── rooms/service.py          # E2EE DM on connection accept
├── encryption/service.py     # Device trust, key backup metadata
├── events/service.py         # com.paripath.* custom events
├── search/service.py         # Synapse message search + local attachment search
├── notifications/service.py  # Notification preference CRUD
└── moderation/
    ├── service.py            # Block → archive; report → matrix_reports
    └── rate_limit.py         # Redis rate limits

infrastructure/database/repositories/
├── matrix_users.py
├── matrix_rooms.py
├── matrix_devices.py
├── matrix_attachments.py
├── matrix_business_events.py
└── conversations.py          # fn_matrix_room_mappings inbox

v1/routers/chat.py
v1/schemas/chat.py
v1/routers/connections.py     # triggers room provision on accept
v1/routers/blocks.py          # triggers archive on block
v1/routers/reports.py         # triggers matrix_reports link

migrations/007_matrix_chat.sql
migrations/008_matrix_functions.sql

docker/synapse/homeserver.yaml
docker/synapse/log.config
docker/postgres/init-syncv3-db.sh

tests/test_matrix_chat_api.py
```

---

## Local Development Checklist

1. Start stack:
   ```bash
   docker compose up -d postgres redis synapse-db synapse sliding-sync
   ```
2. Apply migrations: `uv run python scripts/run_migrations.py`
3. Generate Synapse admin token (first run creates signing key):
   ```bash
   docker compose exec synapse register_new_matrix_user -c /data/homeserver.yaml -u admin -p admin -a http://localhost:8008
   # Or use existing admin token → set MATRIX_ADMIN_TOKEN in .env
   ```
4. Set in `.env`:
   ```bash
   MATRIX_ENABLED=true
   MATRIX_HOMESERVER_URL=http://localhost:8008
   MATRIX_PUBLIC_HOMESERVER_URL=http://localhost:8008
   MATRIX_SLIDING_SYNC_URL=http://localhost:8090
   MATRIX_ADMIN_TOKEN=syt_...
   MATRIX_SERVER_NAME=matrix.local
   ```
5. Start API: `uv run uvicorn main:app --reload`
6. Verify readiness: `curl http://localhost:8000/health/ready`
7. Sign in two users, create connection, accept → room auto-provisioned
8. Open `/chat` in connect-carry — session bootstrap + encrypted messaging

---

## Security Summary

| Concern | Approach |
|---------|----------|
| Message confidentiality | Megolm E2EE — keys in browser IndexedDB only |
| User provisioning | Admin API only; no public registration |
| Password storage | Encrypted at rest in Postgres; never sent to client |
| Session tokens | Short-lived; cached in Redis with TTL cap |
| Block/report | Archives room; links reports to Matrix context |
| Rate limits | BFF Redis limits + Synapse `rc_message` |
| Media | Encrypted MXC URLs on Synapse; BFF stores metadata only |

---

## Relationship to Search (Typesense)

| Concern | System | Doc |
|---------|--------|-----|
| People / travelers / geo search | Typesense via `/v1/search/*` | [typesense-search-platform.md](./typesense-search-platform.md) |
| Chat message content search | Synapse via `/v1/chat/search/messages` | This document |
| Attachment filename search | Postgres metadata via `/v1/chat/search/attachments` | This document |

These are intentionally separate systems with different data stores and security models.
