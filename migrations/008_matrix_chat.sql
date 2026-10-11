-- Matrix chat schema (replaces tinode_* tables for new deployments).

CREATE TABLE IF NOT EXISTS matrix_user_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mxid TEXT NOT NULL UNIQUE,
    localpart TEXT NOT NULL,
    password_encrypted TEXT NOT NULL DEFAULT '',
    provision_status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT matrix_user_mappings_user_unique UNIQUE (user_id),
    CONSTRAINT matrix_user_mappings_localpart_unique UNIQUE (localpart)
);

CREATE TABLE IF NOT EXISTS matrix_room_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_connection_id UUID NOT NULL REFERENCES user_connections(id) ON DELETE CASCADE,
    room_id TEXT NOT NULL,
    room_alias TEXT,
    room_type TEXT NOT NULL DEFAULT 'dm',
    status TEXT NOT NULL DEFAULT 'provisioning',
    business_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT matrix_room_mappings_connection_unique UNIQUE (user_connection_id),
    CONSTRAINT matrix_room_mappings_room_unique UNIQUE (room_id)
);

CREATE TABLE IF NOT EXISTS matrix_user_devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    device_label TEXT,
    trust_level TEXT NOT NULL DEFAULT 'unknown',
    last_seen_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT matrix_user_devices_user_device_unique UNIQUE (user_id, device_id)
);

CREATE TABLE IF NOT EXISTS matrix_key_backup_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    backup_version TEXT NOT NULL,
    algorithm TEXT NOT NULL DEFAULT 'm.megolm_backup.v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT matrix_key_backup_metadata_user_version_unique UNIQUE (user_id, backup_version)
);

CREATE TABLE IF NOT EXISTS matrix_notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    mentions_enabled BOOLEAN NOT NULL DEFAULT true,
    invites_enabled BOOLEAN NOT NULL DEFAULT true,
    messages_enabled BOOLEAN NOT NULL DEFAULT true,
    business_events_enabled BOOLEAN NOT NULL DEFAULT true,
    quiet_hours_start TIME,
    quiet_hours_end TIME,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matrix_attachment_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    mimetype TEXT,
    size_bytes BIGINT,
    sha256 TEXT,
    thumbnail_event_id TEXT,
    uploaded_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT matrix_attachment_metadata_event_unique UNIQUE (room_id, event_id)
);

CREATE TABLE IF NOT EXISTS matrix_business_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    aggregate_id TEXT,
    payload_hash TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT matrix_business_events_event_unique UNIQUE (room_id, event_id)
);

CREATE TABLE IF NOT EXISTS matrix_room_settings (
    room_id TEXT PRIMARY KEY,
    pinned_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    muted BOOLEAN NOT NULL DEFAULT false,
    retention_policy TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matrix_room_archives (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id TEXT NOT NULL,
    archived_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    reason TEXT,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matrix_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID REFERENCES user_reports(id) ON DELETE CASCADE,
    room_id TEXT,
    event_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_matrix_room_mappings_room ON matrix_room_mappings(room_id);
CREATE INDEX IF NOT EXISTS idx_matrix_user_devices_user ON matrix_user_devices(user_id);
CREATE INDEX IF NOT EXISTS idx_matrix_attachment_metadata_room ON matrix_attachment_metadata(room_id);
CREATE INDEX IF NOT EXISTS idx_matrix_business_events_room ON matrix_business_events(room_id);

-- Migrate legacy tinode rows when present.
INSERT INTO matrix_user_mappings (user_id, mxid, localpart, password_encrypted, provision_status)
SELECT
    tum.user_id,
    '@' || tum.tinode_user_id || ':legacy',
    tum.tinode_user_id,
    '',
    'legacy'
FROM tinode_user_mappings tum
WHERE NOT EXISTS (
    SELECT 1 FROM matrix_user_mappings mum WHERE mum.user_id = tum.user_id
)
ON CONFLICT DO NOTHING;

INSERT INTO matrix_room_mappings (
    user_connection_id,
    room_id,
    room_alias,
    room_type,
    status,
    created_by_user_id,
    created_at,
    updated_at
)
SELECT
    tcm.user_connection_id,
    tcm.tinode_topic_id,
    tcm.tinode_topic_name,
    'dm',
    CASE WHEN tcm.status = 'archived' THEN 'archived' ELSE tcm.status END,
    tcm.created_by_user_id,
    tcm.created_at,
    tcm.updated_at
FROM tinode_conversation_mappings tcm
WHERE NOT EXISTS (
    SELECT 1 FROM matrix_room_mappings mrm
    WHERE mrm.user_connection_id = tcm.user_connection_id
)
ON CONFLICT DO NOTHING;

-- Fresh setups only: interactive device sessions are owned by a BFF session.
CREATE TABLE IF NOT EXISTS matrix_sessions (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 bff_session_id UUID NOT NULL REFERENCES auth_sessions(id) ON DELETE CASCADE,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 mxid TEXT NOT NULL,
 device_id TEXT NOT NULL CHECK (device_id <> ''),
 access_token_encrypted TEXT NOT NULL,
 refresh_token_encrypted TEXT,
 expires_at TIMESTAMPTZ,
 status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(mxid, device_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS matrix_sessions_active_bff ON matrix_sessions(bff_session_id)
 WHERE status='active';
CREATE TABLE IF NOT EXISTS matrix_login_attempts (
 state_hash TEXT PRIMARY KEY,
 bff_session_id UUID NOT NULL REFERENCES auth_sessions(id) ON DELETE CASCADE,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 mxid TEXT NOT NULL,
 device_id TEXT NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 consumed_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS matrix_room_operations (
 connection_id UUID PRIMARY KEY REFERENCES user_connections(id) ON DELETE CASCADE,
 creator_user_id UUID NOT NULL REFERENCES users(id),
 status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','complete')),
 attempts INT NOT NULL DEFAULT 0,
 next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 last_error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
