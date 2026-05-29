-- Mode-based functions for social tables (005-010).
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
        'traveler_discovery_snapshot',
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
       OR ctx.account_mode NOT IN ('traveler', 'both') THEN
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

-- fn_traveler_profiles: 1=get, 2=upsert+rebuild
CREATE OR REPLACE FUNCTION fn_traveler_profiles(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result traveler_profiles%ROWTYPE;
    uid UUID;
BEGIN
    uid := (payload->>'user_id')::uuid;

    IF mode = 1 THEN
        SELECT * INTO result FROM traveler_profiles WHERE user_id = uid;
        RETURN CASE WHEN result.user_id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 2 THEN
        INSERT INTO user_privacy_settings (user_id)
        VALUES (uid)
        ON CONFLICT (user_id) DO NOTHING;

        INSERT INTO traveler_profiles (
            user_id,
            headline,
            bio,
            avatar_url,
            home_country_iso,
            home_city_id,
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
            NULLIF(payload->>'home_country_iso', ''),
            NULLIF(payload->>'home_city_id', '')::uuid,
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
            headline = COALESCE(NULLIF(payload->>'headline', ''), traveler_profiles.headline),
            bio = COALESCE(NULLIF(payload->>'bio', ''), traveler_profiles.bio),
            avatar_url = COALESCE(NULLIF(payload->>'avatar_url', ''), traveler_profiles.avatar_url),
            home_country_iso = COALESCE(
                NULLIF(payload->>'home_country_iso', ''),
                traveler_profiles.home_country_iso
            ),
            home_city_id = COALESCE(
                NULLIF(payload->>'home_city_id', '')::uuid,
                traveler_profiles.home_city_id
            ),
            languages = CASE
                WHEN payload ? 'languages' THEN
                    ARRAY(SELECT jsonb_array_elements_text(payload->'languages'))
                ELSE traveler_profiles.languages
            END,
            interests = CASE
                WHEN payload ? 'interests' THEN
                    ARRAY(SELECT jsonb_array_elements_text(payload->'interests'))
                ELSE traveler_profiles.interests
            END,
            connection_availability = COALESCE(
                NULLIF(payload->>'connection_availability', ''),
                traveler_profiles.connection_availability
            ),
            visibility = COALESCE(
                NULLIF(payload->>'visibility', ''),
                traveler_profiles.visibility
            ),
            last_active_at = now(),
            updated_at = now()
        RETURNING * INTO result;

        PERFORM social_rebuild_discovery_snapshot(uid);
        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_traveler_profiles unknown mode: %', mode;
END;
$$;

-- fn_messenger_profiles: 1=get, 2=upsert
CREATE OR REPLACE FUNCTION fn_messenger_profiles(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result messenger_profiles%ROWTYPE;
    uid UUID;
    dest_countries CHAR(2)[];
BEGIN
    uid := (payload->>'user_id')::uuid;

    IF mode = 1 THEN
        SELECT * INTO result FROM messenger_profiles WHERE user_id = uid;
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

        INSERT INTO messenger_profiles (
            user_id,
            home_country_iso,
            preferred_destination_countries,
            last_search_country_iso,
            last_search_city_id,
            bio
        )
        VALUES (
            uid,
            NULLIF(payload->>'home_country_iso', ''),
            COALESCE(dest_countries, '{}'::char(2)[]),
            NULLIF(payload->>'last_search_country_iso', ''),
            NULLIF(payload->>'last_search_city_id', '')::uuid,
            NULLIF(payload->>'bio', '')
        )
        ON CONFLICT (user_id) DO UPDATE SET
            home_country_iso = COALESCE(
                NULLIF(payload->>'home_country_iso', ''),
                messenger_profiles.home_country_iso
            ),
            preferred_destination_countries = COALESCE(
                dest_countries,
                messenger_profiles.preferred_destination_countries
            ),
            last_search_country_iso = COALESCE(
                NULLIF(payload->>'last_search_country_iso', ''),
                messenger_profiles.last_search_country_iso
            ),
            last_search_city_id = COALESCE(
                NULLIF(payload->>'last_search_city_id', '')::uuid,
                messenger_profiles.last_search_city_id
            ),
            bio = COALESCE(NULLIF(payload->>'bio', ''), messenger_profiles.bio),
            updated_at = now()
        RETURNING * INTO result;

        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_messenger_profiles unknown mode: %', mode;
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
                country_iso,
                city_id,
                sort_order,
                arrival_date,
                departure_date
            )
            VALUES (
                plan.id,
                UPPER(dest->>'country_iso'),
                NULLIF(dest->>'city_id', '')::uuid,
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

-- fn_traveler_current_locations: 1=get, 2=upsert+rebuild
CREATE OR REPLACE FUNCTION fn_traveler_current_locations(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result traveler_current_locations%ROWTYPE;
    uid UUID;
    country CHAR(2);
BEGIN
    uid := (payload->>'user_id')::uuid;

    IF mode = 1 THEN
        SELECT * INTO result FROM traveler_current_locations WHERE user_id = uid;
        RETURN CASE WHEN result.user_id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 2 THEN
        country := UPPER(NULLIF(payload->>'country_iso', ''));

        INSERT INTO traveler_current_locations (
            user_id,
            country_iso,
            city_id,
            latitude,
            longitude,
            source,
            updated_at
        )
        VALUES (
            uid,
            country,
            NULLIF(payload->>'city_id', '')::uuid,
            NULLIF(payload->>'latitude', '')::numeric,
            NULLIF(payload->>'longitude', '')::numeric,
            COALESCE(NULLIF(payload->>'source', ''), 'manual'),
            now()
        )
        ON CONFLICT (user_id) DO UPDATE SET
            country_iso = EXCLUDED.country_iso,
            city_id = EXCLUDED.city_id,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            source = EXCLUDED.source,
            updated_at = now()
        RETURNING * INTO result;

        PERFORM social_rebuild_discovery_snapshot(uid);
        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_traveler_current_locations unknown mode: %', mode;
END;
$$;

-- fn_discovery_snapshots: 1=rebuild, 2=get, 3=search, 4=fetch_by_ids
CREATE OR REPLACE FUNCTION fn_discovery_snapshots(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    uid UUID;
    snap traveler_discovery_snapshots%ROWTYPE;
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
        SELECT * INTO snap FROM traveler_discovery_snapshots WHERE user_id = uid;
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
            FROM traveler_discovery_snapshots s
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
        FROM traveler_discovery_snapshots s
        WHERE s.user_id = ANY(
            ARRAY(SELECT (elem::text)::uuid FROM jsonb_array_elements_text(payload->'user_ids') elem)
        )
          AND s.is_discoverable = true;

        RETURN arr;
    END IF;

    RAISE EXCEPTION 'fn_discovery_snapshots unknown mode: %', mode;
END;
$$;

-- fn_connection_requests: 1=create, 2=get, 3=list_incoming, 4=accept, 5=reject
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
    END IF;

    RAISE EXCEPTION 'fn_connection_requests unknown mode: %', mode;
END;
$$;

-- fn_user_connections: 1=get_by_id, 2=get_between
CREATE OR REPLACE FUNCTION fn_user_connections(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result user_connections%ROWTYPE;
    pair RECORD;
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
    END IF;

    RAISE EXCEPTION 'fn_user_connections unknown mode: %', mode;
END;
$$;

-- fn_user_blocks: 1=is_blocked, 2=create
CREATE OR REPLACE FUNCTION fn_user_blocks(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result user_blocks%ROWTYPE;
    blocked BOOLEAN;
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
    END IF;

    RAISE EXCEPTION 'fn_user_blocks unknown mode: %', mode;
END;
$$;

-- fn_tinode_conversation_mappings (table): 1=get, 2=provision
CREATE OR REPLACE FUNCTION fn_tinode_conversation_mappings(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result tinode_conversation_mappings%ROWTYPE;
    cid UUID;
    topic TEXT;
BEGIN
    cid := (payload->>'user_connection_id')::uuid;

    IF mode = 1 THEN
        SELECT * INTO result
        FROM tinode_conversation_mappings
        WHERE user_connection_id = cid;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 2 THEN
        SELECT * INTO result
        FROM tinode_conversation_mappings
        WHERE user_connection_id = cid;

        IF result.id IS NOT NULL THEN
            RETURN to_jsonb(result);
        END IF;

        topic := 'pp_conn_' || cid::text;

        INSERT INTO tinode_conversation_mappings (
            user_connection_id,
            tinode_topic_id,
            tinode_topic_name,
            created_by_user_id,
            status
        )
        VALUES (
            cid,
            topic,
            topic,
            (payload->>'created_by_user_id')::uuid,
            'active'
        )
        RETURNING * INTO result;

        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_tinode_conversation_mappings unknown mode: %', mode;
END;
$$;

-- fn_search_outbox_events: 1=claim, 2=complete, 3=fail
CREATE OR REPLACE FUNCTION fn_search_outbox_events(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    lim INT;
    arr JSONB;
    ev search_outbox_events%ROWTYPE;
BEGIN
    IF mode = 1 THEN
        lim := COALESCE((payload->>'limit')::int, 50);

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
        WHERE id = (payload->>'event_id')::uuid
        RETURNING * INTO ev;

        RETURN CASE WHEN ev.id IS NULL THEN NULL ELSE to_jsonb(ev) END;

    ELSIF mode = 3 THEN
        UPDATE search_outbox_events
        SET status = 'pending',
            last_error = left(payload->>'error', 2000),
            scheduled_at = now() + interval '1 minute' * LEAST(attempts, 30)
        WHERE id = (payload->>'event_id')::uuid
        RETURNING * INTO ev;

        RETURN CASE WHEN ev.id IS NULL THEN NULL ELSE to_jsonb(ev) END;
    END IF;

    RAISE EXCEPTION 'fn_search_outbox_events unknown mode: %', mode;
END;
$$;
