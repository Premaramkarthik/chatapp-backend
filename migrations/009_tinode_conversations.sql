CREATE TABLE IF NOT EXISTS tinode_conversation_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_connection_id UUID NOT NULL REFERENCES user_connections(id) ON DELETE CASCADE,
    tinode_topic_id TEXT NOT NULL,
    tinode_topic_name TEXT,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tinode_conversation_mappings_status_check CHECK (
        status IN ('provisioning', 'active', 'failed', 'archived')
    ),
    CONSTRAINT tinode_conversation_mappings_connection_unique UNIQUE (user_connection_id),
    CONSTRAINT tinode_conversation_mappings_topic_unique UNIQUE (tinode_topic_id)
);

CREATE INDEX IF NOT EXISTS idx_tinode_conversation_mappings_topic
    ON tinode_conversation_mappings(tinode_topic_id);

DROP TRIGGER IF EXISTS trg_tinode_conversation_mappings_set_updated_at ON tinode_conversation_mappings;
CREATE TRIGGER trg_tinode_conversation_mappings_set_updated_at
BEFORE UPDATE ON tinode_conversation_mappings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
