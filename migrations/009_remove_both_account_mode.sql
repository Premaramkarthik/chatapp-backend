-- Remove legacy account_mode 'both' (traveler | messenger only).

UPDATE users
SET account_mode = 'traveler', updated_at = now()
WHERE account_mode = 'both';

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_account_mode_check;
ALTER TABLE users ADD CONSTRAINT users_account_mode_check CHECK (
    account_mode IS NULL
    OR account_mode IN ('traveler', 'messenger')
);

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
        IF payload->>'account_mode' NOT IN ('traveler', 'messenger') THEN
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
    snap traveler_discovery_snapshots%ROWTYPE;
    out_event TEXT;
BEGIN
    SELECT
        u.id AS user_id,
        u.display_name,
        u.status AS user_status,
        u.account_mode,
        tp.headline,
        tp.avatar_url,
        tp.home_country_iso,
        tp.languages,
        tp.interests,
        tp.connection_availability,
        tp.visibility,
        tp.last_active_at,
        COALESCE(ups.allow_search_discovery, true) AS allow_search_discovery,
        COALESCE(ups.show_current_location, true) AS show_current_location,
        COALESCE(ups.show_trip_dates, true) AS show_trip_dates,
        tcl.country_iso AS current_country_iso,
        tcl.city_id AS current_city_id,
        gc_cur.name AS current_city_name,
        tcl.latitude AS current_lat,
        tcl.longitude AS current_lng,
        tplan.start_date AS trip_start_date,
        tplan.end_date AS trip_end_date,
        tdest.country_iso AS destination_country_iso,
        tdest.city_id AS destination_city_id,
        gc_dest.name AS destination_city_name,
        gc_dest.latitude AS dest_lat,
        gc_dest.longitude AS dest_lng
    INTO ctx
    FROM users u
    LEFT JOIN traveler_profiles tp ON tp.user_id = u.id
    LEFT JOIN user_privacy_settings ups ON ups.user_id = u.id
    LEFT JOIN traveler_current_locations tcl ON tcl.user_id = u.id
    LEFT JOIN geo_cities gc_cur ON gc_cur.id = tcl.city_id
    LEFT JOIN LATERAL (
        SELECT id, start_date, end_date
        FROM travel_plans
        WHERE user_id = u.id AND status = 'active'
        ORDER BY is_primary DESC, updated_at DESC
        LIMIT 1
    ) tplan ON true
    LEFT JOIN LATERAL (
        SELECT country_iso, city_id
        FROM travel_plan_destinations
        WHERE travel_plan_id = tplan.id
        ORDER BY sort_order ASC
        LIMIT 1
    ) tdest ON true
    LEFT JOIN geo_cities gc_dest ON gc_dest.id = tdest.city_id
    WHERE u.id = p_user_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    IF ctx.connection_availability IS NULL
       OR ctx.account_mode <> 'traveler' THEN
        DELETE FROM traveler_discovery_snapshots WHERE user_id = p_user_id;
        PERFORM social_enqueue_search_outbox(p_user_id, 'delete');
        RETURN NULL;
    END IF;

    dest_country := COALESCE(ctx.destination_country_iso, ctx.home_country_iso);
    IF dest_country IS NULL THEN
        DELETE FROM traveler_discovery_snapshots WHERE user_id = p_user_id;
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

    INSERT INTO traveler_discovery_snapshots (
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
            (SELECT snapshot_version + 1 FROM traveler_discovery_snapshots WHERE user_id = p_user_id),
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
        snapshot_version = traveler_discovery_snapshots.snapshot_version + 1,
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
