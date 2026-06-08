-- Core domain functions: health, users (modes 1-14), tinode mappings, signup sessions.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fn_health(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
BEGIN
    IF mode = 1 THEN
        RETURN jsonb_build_object('ok', true, 'database_time', now());
    END IF;

    RAISE EXCEPTION 'fn_health unknown mode: %', mode;
END;
$$;

CREATE OR REPLACE FUNCTION fn_tinode_user_mappings(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result tinode_user_mappings%ROWTYPE;
BEGIN
    IF mode = 1 THEN
        IF NULLIF(payload->>'user_id', '') IS NULL THEN
            RAISE EXCEPTION 'user_id is required';
        END IF;
        IF NULLIF(payload->>'tinode_user_id', '') IS NULL THEN
            RAISE EXCEPTION 'tinode_user_id is required';
        END IF;

        INSERT INTO tinode_user_mappings (user_id, tinode_user_id)
        VALUES ((payload->>'user_id')::uuid, payload->>'tinode_user_id')
        ON CONFLICT (user_id) DO UPDATE
        SET
            tinode_user_id = EXCLUDED.tinode_user_id,
            updated_at = now()
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT * INTO result
        FROM tinode_user_mappings
        WHERE user_id = (payload->>'user_id')::uuid
        LIMIT 1;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 3 THEN
        SELECT tum.* INTO result
        FROM tinode_user_mappings tum
        JOIN users u ON u.id = tum.user_id
        WHERE u.keycloak_sub = payload->>'keycloak_sub'
        LIMIT 1;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_tinode_user_mappings unknown mode: %', mode;
END;
$$;

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
          AND (
              keycloak_sub IS NULL
              OR keycloak_sub = payload->>'keycloak_sub'
              OR status = 'pending_verification'
          )
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

        IF result.id IS NULL THEN
            SELECT * INTO result
            FROM users
            WHERE lower(email) = lower(payload->>'email')
              AND status = 'pending_verification'
            LIMIT 1;

            IF result.id IS NOT NULL THEN
                UPDATE users
                SET keycloak_sub = payload->>'keycloak_sub'
                WHERE id = result.id
                RETURNING * INTO result;
            END IF;
        END IF;

        IF result.id IS NULL THEN
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

    ELSIF mode = 13 THEN
        IF NULLIF(payload->>'display_name', '') IS NULL THEN
            RAISE EXCEPTION 'display_name is required';
        END IF;
        IF payload->>'account_mode' NOT IN ('traveler', 'messenger') THEN
            RAISE EXCEPTION 'invalid account_mode';
        END IF;

        UPDATE users
        SET
            display_name = payload->>'display_name',
            account_mode = payload->>'account_mode',
            onboarding_completed_at = now(),
            status = 'active'
        WHERE id = (payload->>'user_id')::uuid
          AND status = 'pending_profile_setup'
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 14 THEN
        DELETE FROM users
        WHERE keycloak_sub = payload->>'keycloak_sub'
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_users unknown mode: %', mode;
END;
$$;
