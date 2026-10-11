-- Search analytics events (source of truth for popularity rollups)

CREATE TABLE IF NOT EXISTS search_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    query TEXT NOT NULL,
    result_type TEXT NOT NULL,
    result_id TEXT,
    clicked BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_events_user_created
    ON search_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_search_events_query_created
    ON search_events (query, created_at);

CREATE INDEX IF NOT EXISTS idx_search_events_result_type_created
    ON search_events (result_type, created_at);
