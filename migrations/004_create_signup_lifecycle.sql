ALTER TABLE users
ALTER COLUMN keycloak_sub DROP NOT NULL;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN IF NOT EXISTS created_via TEXT NOT NULL DEFAULT 'email',
ADD COLUMN IF NOT EXISTS last_verification_sent_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS verification_send_count INT NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS tos_accepted_at TIMESTAMPTZ;

DROP INDEX IF EXISTS idx_users_email;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
ON users(lower(email))
WHERE email IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_status_check'
    ) THEN
        ALTER TABLE users DROP CONSTRAINT users_status_check;
    END IF;

    ALTER TABLE users
    ADD CONSTRAINT users_status_check
    CHECK (
        status IN (
            'pending_verification',
            'pending_profile_setup',
            'active',
            'restricted',
            'suspended',
            'deleted'
        )
    );

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_created_via_check'
    ) THEN
        ALTER TABLE users
        ADD CONSTRAINT users_created_via_check
        CHECK (created_via IN ('email', 'google', 'apple', 'admin'));
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_users_email_verified ON users(email_verified);
CREATE INDEX IF NOT EXISTS idx_users_created_via ON users(created_via);

ALTER TABLE oauth_signin_states
ADD COLUMN IF NOT EXISTS flow_type TEXT NOT NULL DEFAULT 'signin',
ADD COLUMN IF NOT EXISTS account_mode TEXT,
ADD COLUMN IF NOT EXISTS identity_provider TEXT,
ADD COLUMN IF NOT EXISTS email_hash TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'oauth_signin_states_flow_type_check'
    ) THEN
        ALTER TABLE oauth_signin_states
        ADD CONSTRAINT oauth_signin_states_flow_type_check
        CHECK (flow_type IN ('signin', 'signup'));
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_oauth_signin_states_flow_type
ON oauth_signin_states(flow_type);

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

CREATE INDEX IF NOT EXISTS idx_auth_idempotency_keys_expires_at
ON auth_idempotency_keys(expires_at);

CREATE TABLE IF NOT EXISTS auth_outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_outbox_events_unpublished
ON auth_outbox_events(created_at)
WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS signup_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    step_completed INT NOT NULL DEFAULT 1 CHECK (step_completed IN (1, 2)),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signup_sessions_user_id ON signup_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_signup_sessions_expires_at ON signup_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_signup_sessions_active
ON signup_sessions(token_hash)
WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION fn_signup_sessions(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result signup_sessions%ROWTYPE;
BEGIN
    IF mode = 1 THEN
        INSERT INTO signup_sessions (user_id, token_hash, expires_at)
        VALUES (
            (payload->>'user_id')::uuid,
            payload->>'token_hash',
            (payload->>'expires_at')::timestamptz
        )
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT * INTO result
        FROM signup_sessions
        WHERE token_hash = payload->>'token_hash'
          AND revoked_at IS NULL
          AND expires_at > now()
        LIMIT 1;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 3 THEN
        UPDATE signup_sessions
        SET step_completed = 2,
            revoked_at = now()
        WHERE id = (payload->>'session_id')::uuid
          AND revoked_at IS NULL
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_signup_sessions unknown mode: %', mode;
END;
$$;

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

        INSERT INTO users (keycloak_sub, email, display_name, status)
        VALUES (
            payload->>'keycloak_sub',
            NULLIF(lower(payload->>'email'), ''),
            NULLIF(payload->>'display_name', ''),
            'active'
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
            email = COALESCE(NULLIF(lower(payload->>'email'), ''), email),
            display_name = COALESCE(NULLIF(payload->>'display_name', ''), display_name),
            status = COALESCE(NULLIF(payload->>'status', ''), status),
            account_mode = COALESCE(NULLIF(payload->>'account_mode', ''), account_mode)
        WHERE id = (payload->>'user_id')::uuid
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 5 THEN
        UPDATE users
        SET account_mode = payload->>'account_mode'
        WHERE keycloak_sub = payload->>'keycloak_sub'
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 6 THEN
        SELECT * INTO result
        FROM users
        WHERE lower(email) = lower(payload->>'email')
        LIMIT 1;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 7 THEN
        INSERT INTO users (
            email,
            display_name,
            account_mode,
            status,
            created_via,
            email_verified
        )
        VALUES (
            lower(payload->>'email'),
            NULLIF(payload->>'display_name', ''),
            NULLIF(payload->>'account_mode', ''),
            'pending_verification',
            payload->>'created_via',
            false
        )
        ON CONFLICT (email) DO UPDATE
        SET
            display_name = COALESCE(EXCLUDED.display_name, users.display_name),
            account_mode = COALESCE(EXCLUDED.account_mode, users.account_mode),
            updated_at = now()
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 8 THEN
        UPDATE users
        SET keycloak_sub = payload->>'keycloak_sub'
        WHERE id = (payload->>'user_id')::uuid
          AND (keycloak_sub IS NULL OR keycloak_sub = payload->>'keycloak_sub')
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 9 THEN
        UPDATE users
        SET
            last_verification_sent_at = now(),
            verification_send_count = verification_send_count + 1
        WHERE id = (payload->>'user_id')::uuid
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 10 THEN
        IF COALESCE((payload->>'email_verified')::boolean, false) IS NOT TRUE THEN
            RETURN NULL;
        END IF;

        SELECT * INTO result
        FROM users
        WHERE keycloak_sub = payload->>'keycloak_sub'
          AND lower(email) = lower(payload->>'email')
          AND status = 'pending_verification'
        LIMIT 1;

        IF result.id IS NULL
           OR result.display_name IS NULL
           OR result.account_mode IS NULL THEN
            RETURN NULL;
        END IF;

        UPDATE users
        SET
            status = CASE
                WHEN onboarding_completed_at IS NULL THEN 'pending_profile_setup'
                ELSE 'active'
            END,
            email_verified = true
        WHERE id = result.id
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 11 THEN
        UPDATE users
        SET status = 'restricted'
        WHERE id = (payload->>'user_id')::uuid
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 12 THEN
        IF NULLIF(payload->>'display_name', '') IS NULL THEN
            RAISE EXCEPTION 'display_name is required';
        END IF;
        IF payload->>'account_mode' NOT IN ('traveler', 'messenger', 'both') THEN
            RAISE EXCEPTION 'invalid account_mode';
        END IF;

        UPDATE users
        SET
            display_name = payload->>'display_name',
            account_mode = payload->>'account_mode',
            onboarding_completed_at = now()
        WHERE id = (payload->>'user_id')::uuid
          AND status = 'pending_verification'
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_users unknown mode: %', mode;
END;
$$;
