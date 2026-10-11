-- Core identity
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keycloak_sub TEXT UNIQUE,
    email TEXT,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    account_mode TEXT,
    email_verified BOOLEAN NOT NULL DEFAULT false,
    created_via TEXT NOT NULL DEFAULT 'email',
    last_verification_sent_at TIMESTAMPTZ,
    verification_send_count INT NOT NULL DEFAULT 0,
    onboarding_completed_at TIMESTAMPTZ,
    tos_accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tinode_user_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tinode_user_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tinode_user_mappings_user_unique UNIQUE (user_id)
);

-- Auth and signup
CREATE TABLE IF NOT EXISTS oauth_signin_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state_hash TEXT NOT NULL UNIQUE,
    nonce_hash TEXT NOT NULL,
    code_verifier_encrypted TEXT NOT NULL,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    post_signin_redirect_uri TEXT NOT NULL,
    flow_type TEXT NOT NULL DEFAULT 'signin',
    account_mode TEXT,
    identity_provider TEXT,
    email_hash TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_hash TEXT NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    keycloak_sub TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    keycloak_session_id TEXT NOT NULL,
    authenticated_at TIMESTAMPTZ NOT NULL,
    token_version BIGINT NOT NULL DEFAULT 0,
    refresh_owner UUID,
    refresh_lease_until TIMESTAMPTZ,
    access_token_encrypted TEXT NOT NULL,
    refresh_token_encrypted TEXT,
    id_token_encrypted TEXT,
    access_expires_at TIMESTAMPTZ NOT NULL,
    refresh_expires_at TIMESTAMPTZ,
    idle_expires_at TIMESTAMPTZ NOT NULL,
    max_expires_at TIMESTAMPTZ NOT NULL,
    csrf_token_hash TEXT,
    device_label TEXT,
    ip_hash TEXT,
    user_agent_hash TEXT,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_security_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    keycloak_sub TEXT,
    email_hash TEXT,
    ip_hash TEXT,
    user_agent_hash TEXT,
    request_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_device_fingerprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fingerprint_hash TEXT NOT NULL,
    device_label TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT auth_device_fingerprints_user_fingerprint_unique
        UNIQUE (user_id, fingerprint_hash)
);

CREATE TABLE IF NOT EXISTS auth_idempotency_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key_hash TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    response_body JSONB NOT NULL,
    status_code INT NOT NULL,
    email_hash TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signup_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    step_completed INT NOT NULL DEFAULT 1,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Geographic reference (master data; populated via scripts/sync_geo_from_csc.py)
CREATE TABLE IF NOT EXISTS geo_countries (
    id BIGSERIAL PRIMARY KEY,
    iso2 CHAR(2) NOT NULL UNIQUE,
    iso3 CHAR(3) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    phone_code VARCHAR(10),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS geo_states (
    id BIGSERIAL PRIMARY KEY,
    country_id BIGINT NOT NULL REFERENCES geo_countries(id) ON DELETE CASCADE,
    state_code VARCHAR(20),
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS geo_cities (
    id BIGSERIAL PRIMARY KEY,
    csc_city_id BIGINT NOT NULL UNIQUE,
    country_id BIGINT NOT NULL REFERENCES geo_countries(id) ON DELETE CASCADE,
    state_id BIGINT NOT NULL REFERENCES geo_states(id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Profiles and privacy
CREATE TABLE IF NOT EXISTS explorer_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    headline TEXT,
    bio TEXT,
    avatar_url TEXT,
    home_country_id BIGINT REFERENCES geo_countries(id),
    home_state_id BIGINT REFERENCES geo_states(id),
    home_city_id BIGINT REFERENCES geo_cities(id),
    custom_home_country_name VARCHAR(100),
    custom_home_state_name VARCHAR(100),
    custom_home_city_name VARCHAR(150),
    languages TEXT[] NOT NULL DEFAULT '{}',
    interests TEXT[] NOT NULL DEFAULT '{}',
    connection_availability TEXT NOT NULL DEFAULT 'open',
    visibility TEXT NOT NULL DEFAULT 'discoverable',
    onboarding_step TEXT,
    profile_completed_at TIMESTAMPTZ,
    last_active_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS connector_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    home_country_id BIGINT REFERENCES geo_countries(id),
    home_state_id BIGINT REFERENCES geo_states(id),
    home_city_id BIGINT REFERENCES geo_cities(id),
    custom_home_country_name VARCHAR(100),
    custom_home_state_name VARCHAR(100),
    custom_home_city_name VARCHAR(150),
    preferred_destination_countries CHAR(2)[] NOT NULL DEFAULT '{}',
    bio TEXT,
    last_search_country_id BIGINT REFERENCES geo_countries(id),
    last_search_state_id BIGINT REFERENCES geo_states(id),
    last_search_city_id BIGINT REFERENCES geo_cities(id),
    custom_last_search_country_name VARCHAR(100),
    custom_last_search_state_name VARCHAR(100),
    custom_last_search_city_name VARCHAR(150),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_privacy_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    allow_connection_requests BOOLEAN NOT NULL DEFAULT true,
    allow_search_discovery BOOLEAN NOT NULL DEFAULT true,
    show_current_location BOOLEAN NOT NULL DEFAULT true,
    show_trip_dates BOOLEAN NOT NULL DEFAULT true,
    show_online_status BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Travel
CREATE TABLE IF NOT EXISTS travel_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    start_date DATE,
    end_date DATE,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS travel_plan_destinations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    travel_plan_id UUID NOT NULL REFERENCES travel_plans(id) ON DELETE CASCADE,
    country_id BIGINT REFERENCES geo_countries(id),
    state_id BIGINT REFERENCES geo_states(id),
    city_id BIGINT REFERENCES geo_cities(id),
    custom_country_name VARCHAR(100),
    custom_state_name VARCHAR(100),
    custom_city_name VARCHAR(150),
    sort_order INT NOT NULL DEFAULT 0,
    arrival_date DATE,
    departure_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS explorer_current_locations (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    country_id BIGINT REFERENCES geo_countries(id),
    state_id BIGINT REFERENCES geo_states(id),
    city_id BIGINT REFERENCES geo_cities(id),
    custom_country_name VARCHAR(100),
    custom_state_name VARCHAR(100),
    custom_city_name VARCHAR(150),
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    source TEXT NOT NULL DEFAULT 'manual',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Social graph and discovery
CREATE TABLE IF NOT EXISTS explorer_discovery_snapshots (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT,
    headline TEXT,
    avatar_url TEXT,
    home_country_iso CHAR(2),
    destination_country_iso CHAR(2),
    destination_city_id BIGINT,
    destination_city_name TEXT,
    current_country_iso CHAR(2),
    current_city_id BIGINT,
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

CREATE TABLE IF NOT EXISTS connection_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    message TEXT,
    expires_at TIMESTAMPTZ,
    responded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_a_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    connection_request_id UUID REFERENCES connection_requests(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'active',
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blocker_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Chat and search
CREATE TABLE IF NOT EXISTS tinode_conversation_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_connection_id UUID NOT NULL REFERENCES user_connections(id) ON DELETE CASCADE,
    tinode_topic_id TEXT NOT NULL,
    tinode_topic_name TEXT,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS search_outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type TEXT NOT NULL DEFAULT 'explorer_discovery_snapshot',
    aggregate_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    last_error TEXT,
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reported_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_account_mode ON users(account_mode);
CREATE INDEX IF NOT EXISTS idx_users_email_verified ON users(email_verified);
CREATE INDEX IF NOT EXISTS idx_users_created_via ON users(created_via);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
    ON users(lower(email))
    WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tinode_user_mappings_user_id ON tinode_user_mappings(user_id);

CREATE INDEX IF NOT EXISTS idx_oauth_signin_states_expires_at ON oauth_signin_states(expires_at);
CREATE INDEX IF NOT EXISTS idx_oauth_signin_states_flow_type ON oauth_signin_states(flow_type);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_keycloak_sub ON auth_sessions(keycloak_sub);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_status ON auth_sessions(status);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_idle_expires_at ON auth_sessions(idle_expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_max_expires_at ON auth_sessions(max_expires_at);

CREATE INDEX IF NOT EXISTS idx_auth_security_events_event_type ON auth_security_events(event_type);
CREATE INDEX IF NOT EXISTS idx_auth_security_events_user_id ON auth_security_events(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_security_events_created_at ON auth_security_events(created_at);

CREATE INDEX IF NOT EXISTS idx_auth_device_fingerprints_user_id ON auth_device_fingerprints(user_id);

CREATE INDEX IF NOT EXISTS idx_auth_idempotency_keys_expires_at ON auth_idempotency_keys(expires_at);

CREATE INDEX IF NOT EXISTS idx_auth_outbox_events_unpublished
    ON auth_outbox_events(created_at)
    WHERE published_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_signup_sessions_user_id ON signup_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_signup_sessions_expires_at ON signup_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_signup_sessions_active
    ON signup_sessions(token_hash)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_geo_countries_name_trgm ON geo_countries USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_geo_states_country ON geo_states(country_id);
CREATE INDEX IF NOT EXISTS idx_geo_states_name_trgm ON geo_states USING gin (name gin_trgm_ops);
CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_states_country_code_unique
    ON geo_states(country_id, state_code)
    WHERE state_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_geo_cities_state ON geo_cities(state_id);
CREATE INDEX IF NOT EXISTS idx_geo_cities_country ON geo_cities(country_id);
CREATE INDEX IF NOT EXISTS idx_geo_cities_name_trgm ON geo_cities USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_geo_cities_state_name ON geo_cities (state_id, name);

CREATE INDEX IF NOT EXISTS idx_explorer_profiles_discoverable
    ON explorer_profiles(visibility, connection_availability)
    WHERE visibility = 'discoverable';
CREATE INDEX IF NOT EXISTS idx_explorer_profiles_home_country ON explorer_profiles(home_country_id);

CREATE INDEX IF NOT EXISTS idx_travel_plans_user_status ON travel_plans(user_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_travel_plans_one_primary_per_user
    ON travel_plans(user_id)
    WHERE is_primary = true AND status = 'active';

CREATE INDEX IF NOT EXISTS idx_travel_plan_destinations_plan
    ON travel_plan_destinations(travel_plan_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_travel_plan_destinations_country ON travel_plan_destinations(country_id);

CREATE INDEX IF NOT EXISTS idx_explorer_current_locations_country ON explorer_current_locations(country_id);

CREATE INDEX IF NOT EXISTS idx_explorer_discovery_dest_country
    ON explorer_discovery_snapshots(destination_country_iso)
    WHERE is_discoverable = true;
CREATE INDEX IF NOT EXISTS idx_explorer_discovery_current_country
    ON explorer_discovery_snapshots(current_country_iso)
    WHERE is_discoverable = true AND current_country_iso IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_connection_requests_recipient_pending
    ON connection_requests(recipient_id, created_at DESC)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_connection_requests_requester
    ON connection_requests(requester_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_connections_user_a ON user_connections(user_a_id);
CREATE INDEX IF NOT EXISTS idx_user_connections_user_b ON user_connections(user_b_id);

CREATE INDEX IF NOT EXISTS idx_user_blocks_blocker ON user_blocks(blocker_id);
CREATE INDEX IF NOT EXISTS idx_user_blocks_blocked ON user_blocks(blocked_id);

CREATE INDEX IF NOT EXISTS idx_tinode_conversation_mappings_topic
    ON tinode_conversation_mappings(tinode_topic_id);

CREATE INDEX IF NOT EXISTS idx_search_outbox_pending
    ON search_outbox_events(scheduled_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_user_reports_reporter ON user_reports(reporter_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_reports_reported ON user_reports(reported_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_reports_status ON user_reports(status);

CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
    ON notifications(user_id, created_at DESC)
    WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON notifications(user_id, created_at DESC);

-- Table constraints (idempotent add)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_status_check') THEN
        ALTER TABLE users ADD CONSTRAINT users_status_check CHECK (
            status IN (
                'pending_verification',
                'pending_profile_setup',
                'active',
                'restricted',
                'suspended',
                'deleted'
            )
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_account_mode_check') THEN
        ALTER TABLE users ADD CONSTRAINT users_account_mode_check CHECK (
            account_mode IS NULL
            OR account_mode IN ('explorer', 'connector')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_created_via_check') THEN
        ALTER TABLE users ADD CONSTRAINT users_created_via_check CHECK (
            created_via IN ('email', 'google', 'apple', 'admin')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_email_key') THEN
        ALTER TABLE users ADD CONSTRAINT users_email_key UNIQUE (email);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'oauth_signin_states_flow_type_check') THEN
        ALTER TABLE oauth_signin_states ADD CONSTRAINT oauth_signin_states_flow_type_check CHECK (
            flow_type IN ('signin', 'signup')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'auth_sessions_status_check') THEN
        ALTER TABLE auth_sessions ADD CONSTRAINT auth_sessions_status_check CHECK (
            status IN ('ACTIVE', 'REFRESHING', 'REVOKED', 'EXPIRED', 'COMPROMISED', 'LOCKED')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'signup_sessions_step_completed_check') THEN
        ALTER TABLE signup_sessions ADD CONSTRAINT signup_sessions_step_completed_check CHECK (
            step_completed IN (1, 2)
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'explorer_profiles_availability_check') THEN
        ALTER TABLE explorer_profiles ADD CONSTRAINT explorer_profiles_availability_check CHECK (
            connection_availability IN ('open', 'limited', 'unavailable')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'explorer_profiles_visibility_check') THEN
        ALTER TABLE explorer_profiles ADD CONSTRAINT explorer_profiles_visibility_check CHECK (
            visibility IN ('discoverable', 'connections_only', 'hidden')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'travel_plans_status_check') THEN
        ALTER TABLE travel_plans ADD CONSTRAINT travel_plans_status_check CHECK (
            status IN ('draft', 'active', 'completed', 'cancelled')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'travel_plans_dates_check') THEN
        ALTER TABLE travel_plans ADD CONSTRAINT travel_plans_dates_check CHECK (
            start_date IS NULL OR end_date IS NULL OR start_date <= end_date
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'travel_plan_destinations_dates_check') THEN
        ALTER TABLE travel_plan_destinations ADD CONSTRAINT travel_plan_destinations_dates_check CHECK (
            arrival_date IS NULL OR departure_date IS NULL OR arrival_date <= departure_date
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'explorer_current_locations_source_check') THEN
        ALTER TABLE explorer_current_locations ADD CONSTRAINT explorer_current_locations_source_check CHECK (
            source IN ('manual', 'gps', 'inferred')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'connection_requests_status_check') THEN
        ALTER TABLE connection_requests ADD CONSTRAINT connection_requests_status_check CHECK (
            status IN ('pending', 'accepted', 'rejected', 'cancelled', 'expired')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'connection_requests_no_self') THEN
        ALTER TABLE connection_requests ADD CONSTRAINT connection_requests_no_self CHECK (
            requester_id <> recipient_id
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'connection_requests_pair_unique') THEN
        ALTER TABLE connection_requests ADD CONSTRAINT connection_requests_pair_unique UNIQUE (
            requester_id, recipient_id
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_connections_status_check') THEN
        ALTER TABLE user_connections ADD CONSTRAINT user_connections_status_check CHECK (
            status IN ('active', 'removed')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_connections_ordered_pair') THEN
        ALTER TABLE user_connections ADD CONSTRAINT user_connections_ordered_pair CHECK (
            user_a_id < user_b_id
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_connections_pair_unique') THEN
        ALTER TABLE user_connections ADD CONSTRAINT user_connections_pair_unique UNIQUE (
            user_a_id, user_b_id
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_blocks_no_self') THEN
        ALTER TABLE user_blocks ADD CONSTRAINT user_blocks_no_self CHECK (
            blocker_id <> blocked_id
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_blocks_pair_unique') THEN
        ALTER TABLE user_blocks ADD CONSTRAINT user_blocks_pair_unique UNIQUE (
            blocker_id, blocked_id
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tinode_conversation_mappings_status_check') THEN
        ALTER TABLE tinode_conversation_mappings ADD CONSTRAINT tinode_conversation_mappings_status_check CHECK (
            status IN ('provisioning', 'active', 'failed', 'archived')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tinode_conversation_mappings_connection_unique') THEN
        ALTER TABLE tinode_conversation_mappings ADD CONSTRAINT tinode_conversation_mappings_connection_unique UNIQUE (
            user_connection_id
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tinode_conversation_mappings_topic_unique') THEN
        ALTER TABLE tinode_conversation_mappings ADD CONSTRAINT tinode_conversation_mappings_topic_unique UNIQUE (
            tinode_topic_id
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'search_outbox_events_type_check') THEN
        ALTER TABLE search_outbox_events ADD CONSTRAINT search_outbox_events_type_check CHECK (
            event_type IN ('upsert', 'delete')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'search_outbox_events_status_check') THEN
        ALTER TABLE search_outbox_events ADD CONSTRAINT search_outbox_events_status_check CHECK (
            status IN ('pending', 'processing', 'completed', 'failed')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_reports_no_self') THEN
        ALTER TABLE user_reports ADD CONSTRAINT user_reports_no_self CHECK (
            reporter_id <> reported_id
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_reports_status_check') THEN
        ALTER TABLE user_reports ADD CONSTRAINT user_reports_status_check CHECK (
            status IN ('open', 'reviewing', 'resolved', 'dismissed')
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_type_check') THEN
        ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (
            type IN (
                'connection_request',
                'connection_accepted',
                'new_message',
                'trip_match',
                'system'
            )
        );
    END IF;
END;
$$;

-- Durable security operations are independent of user deletion.
CREATE TABLE IF NOT EXISTS auth_remote_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'complete')),
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS auth_remote_operations_pending
    ON auth_remote_operations(next_attempt_at) WHERE status = 'pending';
