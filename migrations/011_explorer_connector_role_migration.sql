-- Migrate legacy traveler/messenger domain to explorer/connector.
-- Idempotent: safe on fresh installs (already renamed) and upgraded legacy schemas.

-- 1. Relax CHECK constraint before rewriting account_mode values
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_account_mode_check;

-- 2. account_mode values (legacy traveler/messenger → explorer/connector)
UPDATE users SET account_mode = 'explorer' WHERE account_mode = 'traveler';
UPDATE users SET account_mode = 'connector' WHERE account_mode = 'messenger';
UPDATE oauth_signin_states SET account_mode = 'explorer' WHERE account_mode = 'traveler';
UPDATE oauth_signin_states SET account_mode = 'connector' WHERE account_mode = 'messenger';

-- 3. Restore CHECK constraint for explorer/connector only
ALTER TABLE users ADD CONSTRAINT users_account_mode_check CHECK (
    account_mode IS NULL
    OR account_mode IN ('explorer', 'connector')
);

-- 4. Rename profile and discovery tables when legacy names exist
DO $$
BEGIN
    IF to_regclass('public.traveler_profiles') IS NOT NULL
       AND to_regclass('public.explorer_profiles') IS NULL THEN
        ALTER TABLE traveler_profiles RENAME TO explorer_profiles;
    END IF;

    IF to_regclass('public.messenger_profiles') IS NOT NULL
       AND to_regclass('public.connector_profiles') IS NULL THEN
        ALTER TABLE messenger_profiles RENAME TO connector_profiles;
    END IF;

    IF to_regclass('public.traveler_current_locations') IS NOT NULL
       AND to_regclass('public.explorer_current_locations') IS NULL THEN
        ALTER TABLE traveler_current_locations RENAME TO explorer_current_locations;
    END IF;

    IF to_regclass('public.traveler_discovery_snapshots') IS NOT NULL
       AND to_regclass('public.explorer_discovery_snapshots') IS NULL THEN
        ALTER TABLE traveler_discovery_snapshots RENAME TO explorer_discovery_snapshots;
    END IF;
END;
$$;

-- 4. Rename legacy constraints when present (skip if already migrated or fresh install)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE c.conname = 'traveler_profiles_availability_check'
          AND t.relname = 'explorer_profiles'
    ) THEN
        ALTER TABLE explorer_profiles
            RENAME CONSTRAINT traveler_profiles_availability_check
            TO explorer_profiles_availability_check;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE c.conname = 'traveler_profiles_visibility_check'
          AND t.relname = 'explorer_profiles'
    ) THEN
        ALTER TABLE explorer_profiles
            RENAME CONSTRAINT traveler_profiles_visibility_check
            TO explorer_profiles_visibility_check;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE c.conname = 'traveler_current_locations_source_check'
          AND t.relname = 'explorer_current_locations'
    ) THEN
        ALTER TABLE explorer_current_locations
            RENAME CONSTRAINT traveler_current_locations_source_check
            TO explorer_current_locations_source_check;
    END IF;
END;
$$;

-- 5. Outbox aggregate type
UPDATE search_outbox_events
SET aggregate_type = 'explorer_discovery_snapshot'
WHERE aggregate_type = 'traveler_discovery_snapshot';

ALTER TABLE search_outbox_events
    ALTER COLUMN aggregate_type SET DEFAULT 'explorer_discovery_snapshot';

-- 6. Triggers (drop legacy names, ensure current)
DROP TRIGGER IF EXISTS trg_traveler_profiles_set_updated_at ON explorer_profiles;
DROP TRIGGER IF EXISTS trg_messenger_profiles_set_updated_at ON connector_profiles;

DROP TRIGGER IF EXISTS trg_explorer_profiles_set_updated_at ON explorer_profiles;
CREATE TRIGGER trg_explorer_profiles_set_updated_at
BEFORE UPDATE ON explorer_profiles
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_connector_profiles_set_updated_at ON connector_profiles;
CREATE TRIGGER trg_connector_profiles_set_updated_at
BEFORE UPDATE ON connector_profiles
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- 7. Drop legacy SQL function names
DROP FUNCTION IF EXISTS fn_traveler_profiles(INT, JSONB);
DROP FUNCTION IF EXISTS fn_messenger_profiles(INT, JSONB);
DROP FUNCTION IF EXISTS fn_traveler_current_locations(INT, JSONB);

-- Re-apply fn_users (explorer/connector account_mode validation)
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

        IF result.id IS NULL THEN
            RETURN NULL;
        END IF;

        IF payload->>'account_mode' NOT IN ('explorer', 'connector') THEN
            RAISE EXCEPTION 'invalid account_mode';
        END IF;

        PERFORM social_bootstrap_role_context(result.id, payload->>'account_mode');

        RETURN to_jsonb(result);

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
                  AND (keycloak_sub IS NULL OR keycloak_sub = payload->>'keycloak_sub')
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
        IF payload->>'account_mode' NOT IN ('explorer', 'connector') THEN
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
        IF payload->>'account_mode' NOT IN ('explorer', 'connector') THEN
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

-- fn_geo: read-only geographic reference search and lookup
--   1=search_countries, 2=search_states, 3=search_cities
--   4=get_country, 5=get_state, 6=get_city
CREATE OR REPLACE FUNCTION fn_geo(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    search_term TEXT;
    pattern TEXT;
    limit_val INT;
    country_id_val BIGINT;
    state_id_val BIGINT;
    entity_id BIGINT;
    items JSONB;
    row_json JSONB;
BEGIN
    limit_val := COALESCE((payload->>'limit')::int, 20);
    IF limit_val < 1 THEN
        limit_val := 1;
    END IF;

    search_term := NULLIF(TRIM(payload->>'search'), '');
    IF search_term IS NOT NULL THEN
        pattern := '%' || search_term || '%';
    END IF;

    IF mode = 1 THEN
        IF pattern IS NOT NULL THEN
            SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', c.id,
                        'iso2', c.iso2,
                        'iso3', c.iso3,
                        'name', c.name,
                        'phone_code', c.phone_code
                    )
                    ORDER BY c.name
                ),
                '[]'::jsonb
            )
            INTO items
            FROM (
                SELECT id, iso2, iso3, name, phone_code
                FROM geo_countries
                WHERE name ILIKE pattern
                   OR iso2 ILIKE pattern
                   OR iso3 ILIKE pattern
                ORDER BY name
                LIMIT limit_val
            ) c;
        ELSE
            SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', c.id,
                        'iso2', c.iso2,
                        'iso3', c.iso3,
                        'name', c.name,
                        'phone_code', c.phone_code
                    )
                    ORDER BY c.name
                ),
                '[]'::jsonb
            )
            INTO items
            FROM (
                SELECT id, iso2, iso3, name, phone_code
                FROM geo_countries
                ORDER BY name
                LIMIT limit_val
            ) c;
        END IF;
        RETURN items;

    ELSIF mode = 2 THEN
        country_id_val := (payload->>'country_id')::bigint;
        IF country_id_val IS NULL THEN
            RAISE EXCEPTION 'country_id is required';
        END IF;

        IF pattern IS NOT NULL THEN
            SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', s.id,
                        'country_id', s.country_id,
                        'state_code', s.state_code,
                        'name', s.name
                    )
                    ORDER BY s.name
                ),
                '[]'::jsonb
            )
            INTO items
            FROM (
                SELECT id, country_id, state_code, name
                FROM geo_states
                WHERE country_id = country_id_val
                  AND (name ILIKE pattern OR state_code ILIKE pattern)
                ORDER BY name
                LIMIT limit_val
            ) s;
        ELSE
            SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', s.id,
                        'country_id', s.country_id,
                        'state_code', s.state_code,
                        'name', s.name
                    )
                    ORDER BY s.name
                ),
                '[]'::jsonb
            )
            INTO items
            FROM (
                SELECT id, country_id, state_code, name
                FROM geo_states
                WHERE country_id = country_id_val
                ORDER BY name
                LIMIT limit_val
            ) s;
        END IF;
        RETURN items;

    ELSIF mode = 3 THEN
        state_id_val := (payload->>'state_id')::bigint;
        IF state_id_val IS NULL THEN
            RAISE EXCEPTION 'state_id is required';
        END IF;

        IF pattern IS NOT NULL THEN
            SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', c.id,
                        'country_id', c.country_id,
                        'state_id', c.state_id,
                        'name', c.name
                    )
                    ORDER BY c.name
                ),
                '[]'::jsonb
            )
            INTO items
            FROM (
                SELECT id, country_id, state_id, name
                FROM geo_cities
                WHERE state_id = state_id_val
                  AND name ILIKE pattern
                ORDER BY name
                LIMIT limit_val
            ) c;
        ELSE
            SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', c.id,
                        'country_id', c.country_id,
                        'state_id', c.state_id,
                        'name', c.name
                    )
                    ORDER BY c.name
                ),
                '[]'::jsonb
            )
            INTO items
            FROM (
                SELECT id, country_id, state_id, name
                FROM geo_cities
                WHERE state_id = state_id_val
                ORDER BY name
                LIMIT limit_val
            ) c;
        END IF;
        RETURN items;

    ELSIF mode = 4 THEN
        entity_id := (payload->>'country_id')::bigint;
        IF entity_id IS NULL THEN
            RAISE EXCEPTION 'country_id is required';
        END IF;

        SELECT jsonb_build_object(
            'id', id,
            'iso2', iso2,
            'iso3', iso3,
            'name', name,
            'phone_code', phone_code
        )
        INTO row_json
        FROM geo_countries
        WHERE id = entity_id;

        RETURN row_json;

    ELSIF mode = 5 THEN
        entity_id := (payload->>'state_id')::bigint;
        IF entity_id IS NULL THEN
            RAISE EXCEPTION 'state_id is required';
        END IF;

        SELECT jsonb_build_object(
            'id', id,
            'country_id', country_id,
            'state_code', state_code,
            'name', name
        )
        INTO row_json
        FROM geo_states
        WHERE id = entity_id;

        RETURN row_json;

    ELSIF mode = 6 THEN
        entity_id := (payload->>'city_id')::bigint;
        IF entity_id IS NULL THEN
            RAISE EXCEPTION 'city_id is required';
        END IF;

        SELECT jsonb_build_object(
            'id', id,
            'country_id', country_id,
            'state_id', state_id,
            'name', name
        )
        INTO row_json
        FROM geo_cities
        WHERE id = entity_id;

        RETURN row_json;
    END IF;

    RAISE EXCEPTION 'fn_geo unknown mode: %', mode;
END;
$$;

-- Re-apply social/discovery functions for renamed tables
-- Social and discovery mode-based functions.
-- Call via: SELECT fn_*(mode INT, payload JSONB)

-- social_ordered_pair: (user_a_id, user_b_id) with user_a < user_b
CREATE OR REPLACE FUNCTION social_ordered_pair(p_user_a UUID, p_user_b UUID)
RETURNS TABLE(user_a_id UUID, user_b_id UUID)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_user_a < p_user_b THEN
        user_a_id := p_user_a;
        user_b_id := p_user_b;
    ELSE
        user_a_id := p_user_b;
        user_b_id := p_user_a;
    END IF;
    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION social_enqueue_search_outbox(p_user_id UUID, p_event_type TEXT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO search_outbox_events (
        aggregate_type,
        aggregate_id,
        event_type,
        payload,
        status,
        scheduled_at
    )
    VALUES (
        'explorer_discovery_snapshot',
        p_user_id,
        p_event_type,
        jsonb_build_object('user_id', p_user_id::text),
        'pending',
        now()
    );
END;
$$;

CREATE OR REPLACE FUNCTION social_rebuild_discovery_snapshot(p_user_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    ctx RECORD;
    dest_country CHAR(2);
    geo_lat NUMERIC(9, 6);
    geo_lng NUMERIC(9, 6);
    avail TEXT;
    vis TEXT;
    is_disc BOOLEAN;
    snap explorer_discovery_snapshots%ROWTYPE;
    out_event TEXT;
BEGIN
    SELECT
        u.id AS user_id,
        u.display_name,
        u.status AS user_status,
        u.account_mode,
        tp.headline,
        tp.avatar_url,
        gc_home.iso2 AS home_country_iso,
        tp.languages,
        tp.interests,
        tp.connection_availability,
        tp.visibility,
        tp.last_active_at,
        COALESCE(ups.allow_search_discovery, true) AS allow_search_discovery,
        COALESCE(ups.show_current_location, true) AS show_current_location,
        COALESCE(ups.show_trip_dates, true) AS show_trip_dates,
        gc_cur_ctry.iso2 AS current_country_iso,
        tcl.city_id AS current_city_id,
        COALESCE(tcl.custom_city_name, gc_cur.name) AS current_city_name,
        tcl.latitude AS current_lat,
        tcl.longitude AS current_lng,
        tplan.start_date AS trip_start_date,
        tplan.end_date AS trip_end_date,
        gc_dest_ctry.iso2 AS destination_country_iso,
        tdest.city_id AS destination_city_id,
        COALESCE(tdest.custom_city_name, gc_dest.name) AS destination_city_name,
        NULL::numeric AS dest_lat,
        NULL::numeric AS dest_lng
    INTO ctx
    FROM users u
    LEFT JOIN explorer_profiles tp ON tp.user_id = u.id
    LEFT JOIN geo_countries gc_home ON gc_home.id = tp.home_country_id
    LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
    LEFT JOIN explorer_current_locations tcl ON tcl.user_id = u.id
    LEFT JOIN geo_cities gc_cur ON gc_cur.id = tcl.city_id
    LEFT JOIN geo_countries gc_cur_ctry ON gc_cur_ctry.id = tcl.country_id
    LEFT JOIN LATERAL (
        SELECT id, start_date, end_date
        FROM travel_plans
        WHERE user_id = u.id AND status = 'active'
        ORDER BY is_primary DESC, updated_at DESC
        LIMIT 1
    ) tplan ON true
    LEFT JOIN LATERAL (
        SELECT country_id, city_id, custom_city_name
        FROM travel_plan_destinations
        WHERE travel_plan_id = tplan.id
        ORDER BY sort_order ASC
        LIMIT 1
    ) tdest ON true
    LEFT JOIN geo_cities gc_dest ON gc_dest.id = tdest.city_id
    LEFT JOIN geo_countries gc_dest_ctry ON gc_dest_ctry.id = tdest.country_id
    WHERE u.id = p_user_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    IF ctx.connection_availability IS NULL
       OR ctx.account_mode <> 'explorer' THEN
        DELETE FROM explorer_discovery_snapshots WHERE user_id = p_user_id;
        PERFORM social_enqueue_search_outbox(p_user_id, 'delete');
        RETURN NULL;
    END IF;

    dest_country := COALESCE(ctx.destination_country_iso, ctx.home_country_iso);
    IF dest_country IS NULL
       AND ctx.destination_city_name IS NULL
       AND ctx.destination_city_id IS NULL THEN
        DELETE FROM explorer_discovery_snapshots WHERE user_id = p_user_id;
        PERFORM social_enqueue_search_outbox(p_user_id, 'delete');
        RETURN NULL;
    END IF;

    avail := COALESCE(ctx.connection_availability, 'open');
    vis := COALESCE(ctx.visibility, 'discoverable');
    is_disc := (
        ctx.user_status = 'active'
        AND COALESCE(ctx.allow_search_discovery, true)
        AND vis = 'discoverable'
        AND avail <> 'unavailable'
    );

    geo_lat := COALESCE(ctx.dest_lat, ctx.current_lat);
    geo_lng := COALESCE(ctx.dest_lng, ctx.current_lng);

    INSERT INTO explorer_discovery_snapshots (
        user_id,
        display_name,
        headline,
        avatar_url,
        home_country_iso,
        destination_country_iso,
        destination_city_id,
        destination_city_name,
        current_country_iso,
        current_city_id,
        current_city_name,
        geo_lat,
        geo_lng,
        trip_start_date,
        trip_end_date,
        languages,
        interests,
        connection_availability,
        visibility,
        is_discoverable,
        last_active_at,
        snapshot_version,
        updated_at
    )
    VALUES (
        p_user_id,
        ctx.display_name,
        ctx.headline,
        ctx.avatar_url,
        ctx.home_country_iso,
        dest_country,
        ctx.destination_city_id,
        ctx.destination_city_name,
        CASE WHEN ctx.show_current_location THEN ctx.current_country_iso ELSE NULL END,
        CASE WHEN ctx.show_current_location THEN ctx.current_city_id ELSE NULL END,
        CASE WHEN ctx.show_current_location THEN ctx.current_city_name ELSE NULL END,
        geo_lat,
        geo_lng,
        CASE WHEN ctx.show_trip_dates THEN ctx.trip_start_date ELSE NULL END,
        CASE WHEN ctx.show_trip_dates THEN ctx.trip_end_date ELSE NULL END,
        COALESCE(ctx.languages, '{}'),
        COALESCE(ctx.interests, '{}'),
        avail,
        vis,
        is_disc,
        ctx.last_active_at,
        COALESCE(
            (SELECT snapshot_version + 1 FROM explorer_discovery_snapshots WHERE user_id = p_user_id),
            1
        ),
        now()
    )
    ON CONFLICT (user_id) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        headline = EXCLUDED.headline,
        avatar_url = EXCLUDED.avatar_url,
        home_country_iso = EXCLUDED.home_country_iso,
        destination_country_iso = EXCLUDED.destination_country_iso,
        destination_city_id = EXCLUDED.destination_city_id,
        destination_city_name = EXCLUDED.destination_city_name,
        current_country_iso = EXCLUDED.current_country_iso,
        current_city_id = EXCLUDED.current_city_id,
        current_city_name = EXCLUDED.current_city_name,
        geo_lat = EXCLUDED.geo_lat,
        geo_lng = EXCLUDED.geo_lng,
        trip_start_date = EXCLUDED.trip_start_date,
        trip_end_date = EXCLUDED.trip_end_date,
        languages = EXCLUDED.languages,
        interests = EXCLUDED.interests,
        connection_availability = EXCLUDED.connection_availability,
        visibility = EXCLUDED.visibility,
        is_discoverable = EXCLUDED.is_discoverable,
        last_active_at = EXCLUDED.last_active_at,
        snapshot_version = explorer_discovery_snapshots.snapshot_version + 1,
        updated_at = now()
    RETURNING * INTO snap;

    IF is_disc AND vis = 'discoverable' THEN
        out_event := 'upsert';
    ELSE
        out_event := 'delete';
    END IF;
    PERFORM social_enqueue_search_outbox(p_user_id, out_event);

    RETURN to_jsonb(snap);
END;
$$;

CREATE OR REPLACE FUNCTION social_expire_connection_request(p_request_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    req connection_requests%ROWTYPE;
BEGIN
    SELECT * INTO req FROM connection_requests WHERE id = p_request_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF req.status = 'pending' AND req.expires_at IS NOT NULL AND req.expires_at < now() THEN
        UPDATE connection_requests
        SET status = 'expired', updated_at = now()
        WHERE id = p_request_id
        RETURNING * INTO req;
    END IF;
    RETURN to_jsonb(req);
END;
$$;

CREATE OR REPLACE FUNCTION social_bootstrap_role_context(
    p_user_id UUID,
    p_account_mode TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_account_mode = 'explorer' THEN
        INSERT INTO user_privacy_settings (user_id)
        VALUES (p_user_id)
        ON CONFLICT (user_id) DO NOTHING;

        INSERT INTO explorer_profiles (
            user_id,
            connection_availability,
            visibility,
            last_active_at
        )
        VALUES (p_user_id, 'open', 'discoverable', now())
        ON CONFLICT (user_id) DO NOTHING;

    ELSIF p_account_mode = 'connector' THEN
        INSERT INTO connector_profiles (
            user_id,
            preferred_destination_countries
        )
        VALUES (p_user_id, '{}'::char(2)[])
        ON CONFLICT (user_id) DO NOTHING;

    ELSE
        RAISE EXCEPTION 'invalid account_mode for bootstrap: %', p_account_mode;
    END IF;
END;
$$;

-- fn_explorer_profiles: 1=get, 2=upsert+rebuild
CREATE OR REPLACE FUNCTION fn_explorer_profiles(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result explorer_profiles%ROWTYPE;
    uid UUID;
BEGIN
    uid := (payload->>'user_id')::uuid;

    IF mode = 1 THEN
        SELECT * INTO result FROM explorer_profiles WHERE user_id = uid;
        RETURN CASE WHEN result.user_id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 2 THEN
        INSERT INTO user_privacy_settings (user_id)
        VALUES (uid)
        ON CONFLICT (user_id) DO NOTHING;

        INSERT INTO explorer_profiles (
            user_id,
            headline,
            bio,
            avatar_url,
            home_country_id,
            home_state_id,
            home_city_id,
            custom_home_country_name,
            custom_home_state_name,
            custom_home_city_name,
            languages,
            interests,
            connection_availability,
            visibility,
            last_active_at
        )
        VALUES (
            uid,
            NULLIF(payload->>'headline', ''),
            NULLIF(payload->>'bio', ''),
            NULLIF(payload->>'avatar_url', ''),
            NULLIF(payload->>'home_country_id', '')::bigint,
            NULLIF(payload->>'home_state_id', '')::bigint,
            NULLIF(payload->>'home_city_id', '')::bigint,
            NULLIF(payload->>'custom_home_country_name', ''),
            NULLIF(payload->>'custom_home_state_name', ''),
            NULLIF(payload->>'custom_home_city_name', ''),
            CASE
                WHEN payload ? 'languages' THEN
                    ARRAY(SELECT jsonb_array_elements_text(payload->'languages'))
                ELSE '{}'::text[]
            END,
            CASE
                WHEN payload ? 'interests' THEN
                    ARRAY(SELECT jsonb_array_elements_text(payload->'interests'))
                ELSE '{}'::text[]
            END,
            COALESCE(NULLIF(payload->>'connection_availability', ''), 'open'),
            COALESCE(NULLIF(payload->>'visibility', ''), 'discoverable'),
            now()
        )
        ON CONFLICT (user_id) DO UPDATE SET
            headline = COALESCE(NULLIF(payload->>'headline', ''), explorer_profiles.headline),
            bio = COALESCE(NULLIF(payload->>'bio', ''), explorer_profiles.bio),
            avatar_url = COALESCE(NULLIF(payload->>'avatar_url', ''), explorer_profiles.avatar_url),
            home_country_id = CASE
                WHEN payload ? 'home_country_id' THEN NULLIF(payload->>'home_country_id', '')::bigint
                ELSE explorer_profiles.home_country_id
            END,
            home_state_id = CASE
                WHEN payload ? 'home_state_id' THEN NULLIF(payload->>'home_state_id', '')::bigint
                ELSE explorer_profiles.home_state_id
            END,
            home_city_id = CASE
                WHEN payload ? 'home_city_id' THEN NULLIF(payload->>'home_city_id', '')::bigint
                ELSE explorer_profiles.home_city_id
            END,
            custom_home_country_name = CASE
                WHEN payload ? 'custom_home_country_name'
                THEN NULLIF(payload->>'custom_home_country_name', '')
                ELSE explorer_profiles.custom_home_country_name
            END,
            custom_home_state_name = CASE
                WHEN payload ? 'custom_home_state_name'
                THEN NULLIF(payload->>'custom_home_state_name', '')
                ELSE explorer_profiles.custom_home_state_name
            END,
            custom_home_city_name = CASE
                WHEN payload ? 'custom_home_city_name'
                THEN NULLIF(payload->>'custom_home_city_name', '')
                ELSE explorer_profiles.custom_home_city_name
            END,
            languages = CASE
                WHEN payload ? 'languages' THEN
                    ARRAY(SELECT jsonb_array_elements_text(payload->'languages'))
                ELSE explorer_profiles.languages
            END,
            interests = CASE
                WHEN payload ? 'interests' THEN
                    ARRAY(SELECT jsonb_array_elements_text(payload->'interests'))
                ELSE explorer_profiles.interests
            END,
            connection_availability = COALESCE(
                NULLIF(payload->>'connection_availability', ''),
                explorer_profiles.connection_availability
            ),
            visibility = COALESCE(
                NULLIF(payload->>'visibility', ''),
                explorer_profiles.visibility
            ),
            last_active_at = now(),
            updated_at = now()
        RETURNING * INTO result;

        PERFORM social_rebuild_discovery_snapshot(uid);
        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_explorer_profiles unknown mode: %', mode;
END;
$$;

-- fn_connector_profiles: 1=get, 2=upsert
CREATE OR REPLACE FUNCTION fn_connector_profiles(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result connector_profiles%ROWTYPE;
    uid UUID;
    dest_countries CHAR(2)[];
BEGIN
    uid := (payload->>'user_id')::uuid;

    IF mode = 1 THEN
        SELECT * INTO result FROM connector_profiles WHERE user_id = uid;
        RETURN CASE WHEN result.user_id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 2 THEN
        IF payload ? 'preferred_destination_countries' THEN
            dest_countries := ARRAY(
                SELECT UPPER(elem::text)
                FROM jsonb_array_elements_text(payload->'preferred_destination_countries') AS elem
            )::char(2)[];
        ELSE
            dest_countries := NULL;
        END IF;

        INSERT INTO connector_profiles (
            user_id,
            home_country_id,
            home_state_id,
            home_city_id,
            custom_home_country_name,
            custom_home_state_name,
            custom_home_city_name,
            preferred_destination_countries,
            last_search_country_id,
            last_search_state_id,
            last_search_city_id,
            custom_last_search_country_name,
            custom_last_search_state_name,
            custom_last_search_city_name,
            bio
        )
        VALUES (
            uid,
            NULLIF(payload->>'home_country_id', '')::bigint,
            NULLIF(payload->>'home_state_id', '')::bigint,
            NULLIF(payload->>'home_city_id', '')::bigint,
            NULLIF(payload->>'custom_home_country_name', ''),
            NULLIF(payload->>'custom_home_state_name', ''),
            NULLIF(payload->>'custom_home_city_name', ''),
            COALESCE(dest_countries, '{}'::char(2)[]),
            NULLIF(payload->>'last_search_country_id', '')::bigint,
            NULLIF(payload->>'last_search_state_id', '')::bigint,
            NULLIF(payload->>'last_search_city_id', '')::bigint,
            NULLIF(payload->>'custom_last_search_country_name', ''),
            NULLIF(payload->>'custom_last_search_state_name', ''),
            NULLIF(payload->>'custom_last_search_city_name', ''),
            NULLIF(payload->>'bio', '')
        )
        ON CONFLICT (user_id) DO UPDATE SET
            home_country_id = COALESCE(
                NULLIF(payload->>'home_country_id', '')::bigint,
                connector_profiles.home_country_id
            ),
            home_state_id = COALESCE(
                NULLIF(payload->>'home_state_id', '')::bigint,
                connector_profiles.home_state_id
            ),
            home_city_id = COALESCE(
                NULLIF(payload->>'home_city_id', '')::bigint,
                connector_profiles.home_city_id
            ),
            custom_home_country_name = COALESCE(
                NULLIF(payload->>'custom_home_country_name', ''),
                connector_profiles.custom_home_country_name
            ),
            custom_home_state_name = COALESCE(
                NULLIF(payload->>'custom_home_state_name', ''),
                connector_profiles.custom_home_state_name
            ),
            custom_home_city_name = COALESCE(
                NULLIF(payload->>'custom_home_city_name', ''),
                connector_profiles.custom_home_city_name
            ),
            preferred_destination_countries = COALESCE(
                dest_countries,
                connector_profiles.preferred_destination_countries
            ),
            last_search_country_id = COALESCE(
                NULLIF(payload->>'last_search_country_id', '')::bigint,
                connector_profiles.last_search_country_id
            ),
            last_search_state_id = COALESCE(
                NULLIF(payload->>'last_search_state_id', '')::bigint,
                connector_profiles.last_search_state_id
            ),
            last_search_city_id = COALESCE(
                NULLIF(payload->>'last_search_city_id', '')::bigint,
                connector_profiles.last_search_city_id
            ),
            custom_last_search_country_name = COALESCE(
                NULLIF(payload->>'custom_last_search_country_name', ''),
                connector_profiles.custom_last_search_country_name
            ),
            custom_last_search_state_name = COALESCE(
                NULLIF(payload->>'custom_last_search_state_name', ''),
                connector_profiles.custom_last_search_state_name
            ),
            custom_last_search_city_name = COALESCE(
                NULLIF(payload->>'custom_last_search_city_name', ''),
                connector_profiles.custom_last_search_city_name
            ),
            bio = COALESCE(NULLIF(payload->>'bio', ''), connector_profiles.bio),
            updated_at = now()
        RETURNING * INTO result;

        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_connector_profiles unknown mode: %', mode;
END;
$$;

-- fn_user_privacy_settings: 1=get, 2=upsert+rebuild
CREATE OR REPLACE FUNCTION fn_user_privacy_settings(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result user_privacy_settings%ROWTYPE;
    uid UUID;
BEGIN
    uid := (payload->>'user_id')::uuid;

    IF mode = 1 THEN
        SELECT * INTO result FROM user_privacy_settings WHERE user_id = uid;
        RETURN CASE WHEN result.user_id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 2 THEN
        INSERT INTO user_privacy_settings (user_id)
        VALUES (uid)
        ON CONFLICT (user_id) DO NOTHING;

        UPDATE user_privacy_settings
        SET
            allow_connection_requests = CASE
                WHEN payload ? 'allow_connection_requests'
                THEN (payload->>'allow_connection_requests')::boolean
                ELSE allow_connection_requests
            END,
            allow_search_discovery = CASE
                WHEN payload ? 'allow_search_discovery'
                THEN (payload->>'allow_search_discovery')::boolean
                ELSE allow_search_discovery
            END,
            show_current_location = CASE
                WHEN payload ? 'show_current_location'
                THEN (payload->>'show_current_location')::boolean
                ELSE show_current_location
            END,
            show_trip_dates = CASE
                WHEN payload ? 'show_trip_dates'
                THEN (payload->>'show_trip_dates')::boolean
                ELSE show_trip_dates
            END,
            show_online_status = CASE
                WHEN payload ? 'show_online_status'
                THEN (payload->>'show_online_status')::boolean
                ELSE show_online_status
            END,
            updated_at = now()
        WHERE user_id = uid
        RETURNING * INTO result;

        IF result.user_id IS NULL THEN
            SELECT * INTO result FROM user_privacy_settings WHERE user_id = uid;
        END IF;

        PERFORM social_rebuild_discovery_snapshot(uid);
        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_user_privacy_settings unknown mode: %', mode;
END;
$$;

-- fn_travel_plans: 1=list, 2=create+destinations+rebuild
CREATE OR REPLACE FUNCTION fn_travel_plans(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    uid UUID;
    plan travel_plans%ROWTYPE;
    dest JSONB;
    idx INT := 0;
    plans_json JSONB;
BEGIN
    uid := (payload->>'user_id')::uuid;

    IF mode = 1 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(tp) ORDER BY tp.is_primary DESC, tp.updated_at DESC), '[]'::jsonb)
        INTO plans_json
        FROM travel_plans tp
        WHERE tp.user_id = uid;
        RETURN plans_json;

    ELSIF mode = 2 THEN
        INSERT INTO travel_plans (
            user_id,
            title,
            start_date,
            end_date,
            is_primary,
            status
        )
        VALUES (
            uid,
            NULLIF(payload->>'title', ''),
            NULLIF(payload->>'start_date', '')::date,
            NULLIF(payload->>'end_date', '')::date,
            COALESCE((payload->>'is_primary')::boolean, true),
            'active'
        )
        RETURNING * INTO plan;

        FOR dest IN SELECT * FROM jsonb_array_elements(payload->'destinations')
        LOOP
            INSERT INTO travel_plan_destinations (
                travel_plan_id,
                country_id,
                state_id,
                city_id,
                custom_country_name,
                custom_state_name,
                custom_city_name,
                sort_order,
                arrival_date,
                departure_date
            )
            VALUES (
                plan.id,
                NULLIF(dest->>'country_id', '')::bigint,
                NULLIF(dest->>'state_id', '')::bigint,
                NULLIF(dest->>'city_id', '')::bigint,
                NULLIF(dest->>'custom_country_name', ''),
                NULLIF(dest->>'custom_state_name', ''),
                NULLIF(dest->>'custom_city_name', ''),
                idx,
                NULLIF(dest->>'arrival_date', '')::date,
                NULLIF(dest->>'departure_date', '')::date
            );
            idx := idx + 1;
        END LOOP;

        PERFORM social_rebuild_discovery_snapshot(uid);
        RETURN to_jsonb(plan);
    END IF;

    RAISE EXCEPTION 'fn_travel_plans unknown mode: %', mode;
END;
$$;

-- fn_explorer_current_locations: 1=get, 2=upsert+rebuild
CREATE OR REPLACE FUNCTION fn_explorer_current_locations(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result explorer_current_locations%ROWTYPE;
    uid UUID;
BEGIN
    uid := (payload->>'user_id')::uuid;

    IF mode = 1 THEN
        SELECT * INTO result FROM explorer_current_locations WHERE user_id = uid;
        RETURN CASE WHEN result.user_id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 2 THEN
        INSERT INTO explorer_current_locations (
            user_id,
            country_id,
            state_id,
            city_id,
            custom_country_name,
            custom_state_name,
            custom_city_name,
            latitude,
            longitude,
            source,
            updated_at
        )
        VALUES (
            uid,
            NULLIF(payload->>'country_id', '')::bigint,
            NULLIF(payload->>'state_id', '')::bigint,
            NULLIF(payload->>'city_id', '')::bigint,
            NULLIF(payload->>'custom_country_name', ''),
            NULLIF(payload->>'custom_state_name', ''),
            NULLIF(payload->>'custom_city_name', ''),
            NULLIF(payload->>'latitude', '')::numeric,
            NULLIF(payload->>'longitude', '')::numeric,
            COALESCE(NULLIF(payload->>'source', ''), 'manual'),
            now()
        )
        ON CONFLICT (user_id) DO UPDATE SET
            country_id = EXCLUDED.country_id,
            state_id = EXCLUDED.state_id,
            city_id = EXCLUDED.city_id,
            custom_country_name = EXCLUDED.custom_country_name,
            custom_state_name = EXCLUDED.custom_state_name,
            custom_city_name = EXCLUDED.custom_city_name,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            source = EXCLUDED.source,
            updated_at = now()
        RETURNING * INTO result;

        PERFORM social_rebuild_discovery_snapshot(uid);
        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_explorer_current_locations unknown mode: %', mode;
END;
$$;

-- fn_discovery_snapshots: 1=rebuild, 2=get, 3=search, 4=fetch_by_ids
CREATE OR REPLACE FUNCTION fn_discovery_snapshots(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    uid UUID;
    snap explorer_discovery_snapshots%ROWTYPE;
    arr JSONB;
    dest_country CHAR(2);
    cur_country CHAR(2);
    viewer UUID;
    lim INT;
    off INT;
BEGIN
    IF mode = 1 THEN
        uid := (payload->>'user_id')::uuid;
        RETURN social_rebuild_discovery_snapshot(uid);

    ELSIF mode = 2 THEN
        uid := (payload->>'user_id')::uuid;
        SELECT * INTO snap FROM explorer_discovery_snapshots WHERE user_id = uid;
        RETURN CASE WHEN snap.user_id IS NULL THEN NULL ELSE to_jsonb(snap) END;

    ELSIF mode = 3 THEN
        dest_country := UPPER(payload->>'destination_country');
        cur_country := UPPER(NULLIF(payload->>'current_country', ''));
        viewer := (payload->>'viewer_id')::uuid;
        lim := COALESCE((payload->>'limit')::int, 20);
        off := COALESCE((payload->>'offset')::int, 0);

        SELECT COALESCE(jsonb_agg(to_jsonb(s) ORDER BY s.last_active_at DESC NULLS LAST), '[]'::jsonb)
        INTO arr
        FROM (
            SELECT s.*
            FROM explorer_discovery_snapshots s
            WHERE s.is_discoverable = true
              AND s.destination_country_iso = dest_country
              AND (cur_country IS NULL OR s.current_country_iso = cur_country)
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks b
                  WHERE (b.blocker_id = viewer AND b.blocked_id = s.user_id)
                     OR (b.blocker_id = s.user_id AND b.blocked_id = viewer)
              )
            ORDER BY s.last_active_at DESC NULLS LAST
            LIMIT lim OFFSET off
        ) s;

        RETURN arr;

    ELSIF mode = 4 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(s)), '[]'::jsonb)
        INTO arr
        FROM explorer_discovery_snapshots s
        WHERE s.user_id = ANY(
            ARRAY(SELECT (elem::text)::uuid FROM jsonb_array_elements_text(payload->'user_ids') elem)
        )
          AND s.is_discoverable = true;

        RETURN arr;
    END IF;

    RAISE EXCEPTION 'fn_discovery_snapshots unknown mode: %', mode;
END;
$$;

-- fn_connection_requests: 1=create, 2=get, 3=list_incoming, 4=accept, 5=reject, 6=cancel, 7=list_outgoing
CREATE OR REPLACE FUNCTION fn_connection_requests(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    req connection_requests%ROWTYPE;
    req_json JSONB;
    conn user_connections%ROWTYPE;
    ttl_days INT;
    expires TIMESTAMPTZ;
    pair RECORD;
    arr JSONB;
    rid UUID;
    recipient UUID;
BEGIN
    IF mode = 1 THEN
        IF EXISTS (
            SELECT 1 FROM user_blocks
            WHERE (blocker_id = (payload->>'requester_id')::uuid
                   AND blocked_id = (payload->>'recipient_id')::uuid)
               OR (blocker_id = (payload->>'recipient_id')::uuid
                   AND blocked_id = (payload->>'requester_id')::uuid)
        ) THEN
            RAISE EXCEPTION 'blocked';
        END IF;

        ttl_days := COALESCE((payload->>'ttl_days')::int, 14);
        expires := now() + (ttl_days || ' days')::interval;

        INSERT INTO connection_requests (
            requester_id,
            recipient_id,
            status,
            message,
            expires_at
        )
        VALUES (
            (payload->>'requester_id')::uuid,
            (payload->>'recipient_id')::uuid,
            'pending',
            NULLIF(payload->>'message', ''),
            expires
        )
        ON CONFLICT (requester_id, recipient_id) DO UPDATE SET
            status = CASE
                WHEN connection_requests.status IN ('rejected', 'cancelled', 'expired')
                THEN 'pending'
                ELSE connection_requests.status
            END,
            message = EXCLUDED.message,
            expires_at = EXCLUDED.expires_at,
            updated_at = now()
        RETURNING * INTO req;

        RETURN to_jsonb(req);

    ELSIF mode = 2 THEN
        rid := (payload->>'request_id')::uuid;
        RETURN social_expire_connection_request(rid);

    ELSIF mode = 3 THEN
        recipient := (payload->>'recipient_id')::uuid;

        UPDATE connection_requests
        SET status = 'expired', updated_at = now()
        WHERE recipient_id = recipient
          AND status = 'pending'
          AND expires_at IS NOT NULL
          AND expires_at < now();

        SELECT COALESCE(jsonb_agg(to_jsonb(cr) ORDER BY cr.created_at DESC), '[]'::jsonb)
        INTO arr
        FROM connection_requests cr
        WHERE cr.recipient_id = recipient AND cr.status = 'pending';

        RETURN arr;

    ELSIF mode = 4 THEN
        rid := (payload->>'request_id')::uuid;
        recipient := (payload->>'recipient_id')::uuid;

        req_json := social_expire_connection_request(rid);
        IF req_json IS NULL THEN
            RAISE EXCEPTION 'not_found';
        END IF;
        req := jsonb_populate_record(NULL::connection_requests, req_json);
        IF req.recipient_id <> recipient THEN
            RAISE EXCEPTION 'forbidden';
        END IF;
        IF req.status <> 'pending' THEN
            RAISE EXCEPTION 'invalid_status';
        END IF;

        UPDATE connection_requests
        SET status = 'accepted', responded_at = now(), updated_at = now()
        WHERE id = rid;

        SELECT * INTO pair FROM social_ordered_pair(req.requester_id, req.recipient_id);

        INSERT INTO user_connections (
            user_a_id,
            user_b_id,
            connection_request_id,
            status
        )
        VALUES (pair.user_a_id, pair.user_b_id, rid, 'active')
        ON CONFLICT (user_a_id, user_b_id) DO UPDATE SET
            status = 'active',
            connection_request_id = EXCLUDED.connection_request_id
        RETURNING * INTO conn;

        RETURN to_jsonb(conn);

    ELSIF mode = 5 THEN
        rid := (payload->>'request_id')::uuid;
        recipient := (payload->>'recipient_id')::uuid;

        UPDATE connection_requests
        SET status = 'rejected', responded_at = now(), updated_at = now()
        WHERE id = rid
          AND recipient_id = recipient
          AND status = 'pending'
        RETURNING * INTO req;

        IF req.id IS NULL THEN
            RAISE EXCEPTION 'not_found';
        END IF;
        RETURN to_jsonb(req);

    ELSIF mode = 6 THEN
        rid := (payload->>'request_id')::uuid;

        UPDATE connection_requests
        SET status = 'cancelled', updated_at = now()
        WHERE id = rid
          AND requester_id = (payload->>'requester_id')::uuid
          AND status = 'pending'
        RETURNING * INTO req;

        IF req.id IS NULL THEN
            RAISE EXCEPTION 'not_found';
        END IF;
        RETURN to_jsonb(req);

    ELSIF mode = 7 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(cr) ORDER BY cr.created_at DESC), '[]'::jsonb)
        INTO arr
        FROM connection_requests cr
        WHERE cr.requester_id = (payload->>'requester_id')::uuid
          AND cr.status = 'pending';

        RETURN arr;
    END IF;

    RAISE EXCEPTION 'fn_connection_requests unknown mode: %', mode;
END;
$$;

-- fn_user_connections: 1=get_by_id, 2=get_between, 3=list_active, 4=remove
CREATE OR REPLACE FUNCTION fn_user_connections(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result user_connections%ROWTYPE;
    pair RECORD;
    arr JSONB;
    uid UUID;
BEGIN
    IF mode = 1 THEN
        SELECT * INTO result
        FROM user_connections
        WHERE id = (payload->>'connection_id')::uuid;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 2 THEN
        SELECT * INTO pair
        FROM social_ordered_pair(
            (payload->>'user_id')::uuid,
            (payload->>'other_user_id')::uuid
        );

        SELECT * INTO result
        FROM user_connections
        WHERE user_a_id = pair.user_a_id
          AND user_b_id = pair.user_b_id
          AND status = 'active';

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 3 THEN
        uid := (payload->>'user_id')::uuid;

        SELECT COALESCE(jsonb_agg(to_jsonb(uc) ORDER BY uc.connected_at DESC), '[]'::jsonb)
        INTO arr
        FROM user_connections uc
        WHERE (uc.user_a_id = uid OR uc.user_b_id = uid)
          AND uc.status = 'active';

        RETURN arr;

    ELSIF mode = 4 THEN
        uid := (payload->>'user_id')::uuid;

        UPDATE user_connections
        SET status = 'removed'
        WHERE id = (payload->>'connection_id')::uuid
          AND status = 'active'
          AND (user_a_id = uid OR user_b_id = uid)
        RETURNING * INTO result;

        IF result.id IS NULL THEN
            RAISE EXCEPTION 'not_found';
        END IF;
        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_user_connections unknown mode: %', mode;
END;
$$;

-- fn_user_blocks: 1=is_blocked, 2=create, 3=list, 4=delete
CREATE OR REPLACE FUNCTION fn_user_blocks(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result user_blocks%ROWTYPE;
    blocked BOOLEAN;
    arr JSONB;
BEGIN
    IF mode = 1 THEN
        SELECT EXISTS (
            SELECT 1 FROM user_blocks
            WHERE (blocker_id = (payload->>'user_id')::uuid
                   AND blocked_id = (payload->>'other_user_id')::uuid)
               OR (blocker_id = (payload->>'other_user_id')::uuid
                   AND blocked_id = (payload->>'user_id')::uuid)
        ) INTO blocked;

        RETURN jsonb_build_object('blocked', blocked);

    ELSIF mode = 2 THEN
        INSERT INTO user_blocks (blocker_id, blocked_id, reason)
        VALUES (
            (payload->>'blocker_id')::uuid,
            (payload->>'blocked_id')::uuid,
            NULLIF(payload->>'reason', '')
        )
        ON CONFLICT (blocker_id, blocked_id) DO UPDATE SET reason = EXCLUDED.reason
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 3 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(b) ORDER BY b.created_at DESC), '[]'::jsonb)
        INTO arr
        FROM user_blocks b
        WHERE b.blocker_id = (payload->>'blocker_id')::uuid;

        RETURN arr;

    ELSIF mode = 4 THEN
        DELETE FROM user_blocks
        WHERE blocker_id = (payload->>'blocker_id')::uuid
          AND blocked_id = (payload->>'blocked_id')::uuid
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_user_blocks unknown mode: %', mode;
END;
$$;

-- fn_user_reports: 1=create, 2=list_for_reporter
CREATE OR REPLACE FUNCTION fn_user_reports(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result user_reports%ROWTYPE;
    arr JSONB;
BEGIN
    IF mode = 1 THEN
        IF (payload->>'reporter_id')::uuid = (payload->>'reported_id')::uuid THEN
            RAISE EXCEPTION 'cannot_report_self';
        END IF;

        INSERT INTO user_reports (
            reporter_id,
            reported_id,
            reason,
            description,
            status
        )
        VALUES (
            (payload->>'reporter_id')::uuid,
            (payload->>'reported_id')::uuid,
            payload->>'reason',
            NULLIF(payload->>'description', ''),
            'open'
        )
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY r.created_at DESC), '[]'::jsonb)
        INTO arr
        FROM user_reports r
        WHERE r.reporter_id = (payload->>'reporter_id')::uuid;

        RETURN arr;
    END IF;

    RAISE EXCEPTION 'fn_user_reports unknown mode: %', mode;
END;
$$;

-- fn_notifications: 1=create, 2=list, 3=mark_read
CREATE OR REPLACE FUNCTION fn_notifications(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result notifications%ROWTYPE;
    arr JSONB;
    uid UUID;
BEGIN
    IF mode = 1 THEN
        INSERT INTO notifications (user_id, type, payload)
        VALUES (
            (payload->>'user_id')::uuid,
            payload->>'type',
            COALESCE(payload->'payload', '{}'::jsonb)
        )
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        uid := (payload->>'user_id')::uuid;

        SELECT COALESCE(jsonb_agg(to_jsonb(n) ORDER BY n.created_at DESC), '[]'::jsonb)
        INTO arr
        FROM notifications n
        WHERE n.user_id = uid
          AND (NOT (payload ? 'unread_only') OR (payload->>'unread_only')::boolean IS NOT TRUE OR n.read_at IS NULL);

        RETURN arr;

    ELSIF mode = 3 THEN
        UPDATE notifications
        SET read_at = now()
        WHERE id = (payload->>'notification_id')::uuid
          AND user_id = (payload->>'user_id')::uuid
          AND read_at IS NULL
        RETURNING * INTO result;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_notifications unknown mode: %', mode;
END;
$$;

-- fn_search_outbox_events: 1=claim, 2=complete, 3=fail
CREATE OR REPLACE FUNCTION fn_search_outbox_events(mode INT, p_payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    lim INT;
    arr JSONB;
    ev search_outbox_events%ROWTYPE;
BEGIN
    IF mode = 1 THEN
        lim := COALESCE((p_payload->>'limit')::int, 50);

        WITH claimed AS (
            UPDATE search_outbox_events
            SET status = 'processing', attempts = attempts + 1
            WHERE id IN (
                SELECT id
                FROM search_outbox_events
                WHERE status = 'pending' AND scheduled_at <= now()
                ORDER BY scheduled_at
                LIMIT lim
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
        )
        SELECT COALESCE(jsonb_agg(to_jsonb(claimed)), '[]'::jsonb)
        INTO arr
        FROM claimed;

        RETURN arr;

    ELSIF mode = 2 THEN
        UPDATE search_outbox_events
        SET status = 'completed', processed_at = now(), last_error = NULL
        WHERE id = (p_payload->>'event_id')::uuid
        RETURNING * INTO ev;

        RETURN CASE WHEN ev.id IS NULL THEN NULL ELSE to_jsonb(ev) END;

    ELSIF mode = 3 THEN
        UPDATE search_outbox_events
        SET status = 'pending',
            last_error = left(p_payload->>'error', 2000),
            scheduled_at = now() + interval '1 minute' * LEAST(attempts, 30)
        WHERE id = (p_payload->>'event_id')::uuid
        RETURNING * INTO ev;

        RETURN CASE WHEN ev.id IS NULL THEN NULL ELSE to_jsonb(ev) END;
    END IF;

    RAISE EXCEPTION 'fn_search_outbox_events unknown mode: %', mode;
END;
$$;
