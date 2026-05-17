CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_users_set_updated_at ON users;
CREATE TRIGGER trg_users_set_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tinode_user_mappings_set_updated_at ON tinode_user_mappings;
CREATE TRIGGER trg_tinode_user_mappings_set_updated_at
BEFORE UPDATE ON tinode_user_mappings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

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
            status = COALESCE(NULLIF(payload->>'status', ''), status)
        WHERE id = (payload->>'user_id')::uuid
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_users unknown mode: %', mode;
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
