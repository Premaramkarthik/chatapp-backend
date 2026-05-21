ALTER TABLE users
ADD COLUMN IF NOT EXISTS account_mode TEXT NOT NULL DEFAULT 'messenger';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_account_mode_check'
    ) THEN
        ALTER TABLE users
        ADD CONSTRAINT users_account_mode_check
        CHECK (account_mode IN ('traveler', 'messenger', 'both'));
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_users_account_mode ON users(account_mode);

CREATE TABLE IF NOT EXISTS oauth_signin_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state_hash TEXT NOT NULL UNIQUE,
    nonce_hash TEXT NOT NULL,
    code_verifier_encrypted TEXT NOT NULL,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    post_signin_redirect_uri TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_oauth_signin_states_expires_at
ON oauth_signin_states(expires_at);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_hash TEXT NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    keycloak_sub TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT auth_sessions_status_check CHECK (
        status IN ('ACTIVE', 'REFRESHING', 'REVOKED', 'EXPIRED', 'COMPROMISED', 'LOCKED')
    )
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_keycloak_sub ON auth_sessions(keycloak_sub);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_status ON auth_sessions(status);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_idle_expires_at ON auth_sessions(idle_expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_max_expires_at ON auth_sessions(max_expires_at);

DROP TRIGGER IF EXISTS trg_auth_sessions_set_updated_at ON auth_sessions;
CREATE TRIGGER trg_auth_sessions_set_updated_at
BEFORE UPDATE ON auth_sessions
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

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

CREATE INDEX IF NOT EXISTS idx_auth_security_events_event_type
ON auth_security_events(event_type);

CREATE INDEX IF NOT EXISTS idx_auth_security_events_user_id
ON auth_security_events(user_id);

CREATE INDEX IF NOT EXISTS idx_auth_security_events_created_at
ON auth_security_events(created_at);

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

CREATE INDEX IF NOT EXISTS idx_auth_device_fingerprints_user_id
ON auth_device_fingerprints(user_id);

DROP TRIGGER IF EXISTS trg_auth_device_fingerprints_set_updated_at ON auth_device_fingerprints;
CREATE TRIGGER trg_auth_device_fingerprints_set_updated_at
BEFORE UPDATE ON auth_device_fingerprints
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION fn_users(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result users%ROWTYPE;
BEGIN
    IF mode = 1 THEN
        IF NULLIF(payload->>'keycloak_sub', '') IS NULL THEN
            RAISE EXCEPTION 'keycloak_sub is required';
        END IF;

        INSERT INTO users (keycloak_sub, email, display_name)
        VALUES (
            payload->>'keycloak_sub',
            NULLIF(payload->>'email', ''),
            NULLIF(payload->>'display_name', '')
        )
        ON CONFLICT (keycloak_sub) DO UPDATE
        SET
            email = COALESCE(EXCLUDED.email, users.email),
            display_name = COALESCE(EXCLUDED.display_name, users.display_name),
            updated_at = now()
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT * INTO result
        FROM users
        WHERE id = (payload->>'user_id')::uuid
        LIMIT 1;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 3 THEN
        SELECT * INTO result
        FROM users
        WHERE keycloak_sub = payload->>'keycloak_sub'
        LIMIT 1;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 4 THEN
        UPDATE users
        SET
            email = COALESCE(NULLIF(payload->>'email', ''), email),
            display_name = COALESCE(NULLIF(payload->>'display_name', ''), display_name),
            status = COALESCE(NULLIF(payload->>'status', ''), status),
            account_mode = COALESCE(NULLIF(payload->>'account_mode', ''), account_mode)
        WHERE id = (payload->>'user_id')::uuid
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 5 THEN
        IF NULLIF(payload->>'keycloak_sub', '') IS NULL THEN
            RAISE EXCEPTION 'keycloak_sub is required';
        END IF;
        IF NULLIF(payload->>'account_mode', '') IS NULL THEN
            RAISE EXCEPTION 'account_mode is required';
        END IF;

        UPDATE users
        SET account_mode = payload->>'account_mode'
        WHERE keycloak_sub = payload->>'keycloak_sub'
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_users unknown mode: %', mode;
END;
$$;
