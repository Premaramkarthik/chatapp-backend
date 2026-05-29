CREATE TABLE IF NOT EXISTS traveler_discovery_snapshots (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT,
    headline TEXT,
    avatar_url TEXT,
    home_country_iso CHAR(2),
    destination_country_iso CHAR(2) NOT NULL,
    destination_city_id UUID,
    destination_city_name TEXT,
    current_country_iso CHAR(2),
    current_city_id UUID,
    current_city_name TEXT,
    geo_lat NUMERIC(9, 6),
    geo_lng NUMERIC(9, 6),
    trip_start_date DATE,
    trip_end_date DATE,
    languages TEXT[] NOT NULL DEFAULT '{}',
    interests TEXT[] NOT NULL DEFAULT '{}',
    connection_availability TEXT NOT NULL DEFAULT 'open',
    visibility TEXT NOT NULL DEFAULT 'discoverable',
    is_discoverable BOOLEAN NOT NULL DEFAULT true,
    last_active_at TIMESTAMPTZ,
    snapshot_version BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_traveler_discovery_dest_country
    ON traveler_discovery_snapshots(destination_country_iso)
    WHERE is_discoverable = true;
CREATE INDEX IF NOT EXISTS idx_traveler_discovery_current_country
    ON traveler_discovery_snapshots(current_country_iso)
    WHERE is_discoverable = true AND current_country_iso IS NOT NULL;

CREATE TABLE IF NOT EXISTS connection_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    message TEXT,
    expires_at TIMESTAMPTZ,
    responded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT connection_requests_status_check CHECK (
        status IN ('pending', 'accepted', 'rejected', 'cancelled', 'expired')
    ),
    CONSTRAINT connection_requests_no_self CHECK (requester_id <> recipient_id),
    CONSTRAINT connection_requests_pair_unique UNIQUE (requester_id, recipient_id)
);

CREATE INDEX IF NOT EXISTS idx_connection_requests_recipient_pending
    ON connection_requests(recipient_id, created_at DESC)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_connection_requests_requester
    ON connection_requests(requester_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_connection_requests_set_updated_at ON connection_requests;
CREATE TRIGGER trg_connection_requests_set_updated_at
BEFORE UPDATE ON connection_requests
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS user_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_a_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    connection_request_id UUID REFERENCES connection_requests(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'active',
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT user_connections_status_check CHECK (status IN ('active', 'removed')),
    CONSTRAINT user_connections_ordered_pair CHECK (user_a_id < user_b_id),
    CONSTRAINT user_connections_pair_unique UNIQUE (user_a_id, user_b_id)
);

CREATE INDEX IF NOT EXISTS idx_user_connections_user_a ON user_connections(user_a_id);
CREATE INDEX IF NOT EXISTS idx_user_connections_user_b ON user_connections(user_b_id);

CREATE TABLE IF NOT EXISTS user_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blocker_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT user_blocks_no_self CHECK (blocker_id <> blocked_id),
    CONSTRAINT user_blocks_pair_unique UNIQUE (blocker_id, blocked_id)
);

CREATE INDEX IF NOT EXISTS idx_user_blocks_blocker ON user_blocks(blocker_id);
CREATE INDEX IF NOT EXISTS idx_user_blocks_blocked ON user_blocks(blocked_id);
