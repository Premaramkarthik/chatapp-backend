-- Matrix chat SQL functions.

CREATE OR REPLACE FUNCTION fn_matrix_user_mappings(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_user_mappings%ROWTYPE;
BEGIN
    IF mode = 1 THEN
        IF NULLIF(payload->>'user_id', '') IS NULL THEN
            RAISE EXCEPTION 'user_id is required';
        END IF;
        IF NULLIF(payload->>'mxid', '') IS NULL THEN
            RAISE EXCEPTION 'mxid is required';
        END IF;

        INSERT INTO matrix_user_mappings (
            user_id, mxid, localpart, password_encrypted, provision_status
        )
        VALUES (
            (payload->>'user_id')::uuid,
            payload->>'mxid',
            COALESCE(NULLIF(payload->>'localpart', ''), split_part(payload->>'mxid', ':', 1)),
            COALESCE(payload->>'password_encrypted', ''),
            COALESCE(NULLIF(payload->>'provision_status', ''), 'active')
        )
        ON CONFLICT (user_id) DO UPDATE
        SET
            mxid = matrix_user_mappings.mxid,
            localpart = matrix_user_mappings.localpart,
            password_encrypted = EXCLUDED.password_encrypted,
            provision_status = EXCLUDED.provision_status,
            updated_at = now()
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT * INTO result
        FROM matrix_user_mappings
        WHERE user_id = (payload->>'user_id')::uuid
        LIMIT 1;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 3 THEN
        SELECT mum.* INTO result
        FROM matrix_user_mappings mum
        JOIN users u ON u.id = mum.user_id
        WHERE u.keycloak_sub = payload->>'keycloak_sub'
        LIMIT 1;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 4 THEN
        SELECT * INTO result
        FROM matrix_user_mappings
        WHERE mxid = payload->>'mxid'
        LIMIT 1;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_matrix_user_mappings unknown mode: %', mode;
END;
$$;

CREATE OR REPLACE FUNCTION fn_matrix_room_mappings(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_room_mappings%ROWTYPE;
    cid UUID;
    uid UUID;
    rows JSONB;
BEGIN
    cid := (payload->>'user_connection_id')::uuid;
    uid := (payload->>'user_id')::uuid;

    IF mode = 1 THEN
        SELECT * INTO result
        FROM matrix_room_mappings
        WHERE user_connection_id = cid;

        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 2 THEN
        SELECT * INTO result
        FROM matrix_room_mappings
        WHERE user_connection_id = cid;

        IF result.id IS NOT NULL THEN
            RETURN to_jsonb(result);
        END IF;

        INSERT INTO matrix_room_mappings (
            user_connection_id,
            room_id,
            room_alias,
            created_by_user_id,
            status
        )
        VALUES (
            cid,
            COALESCE(NULLIF(payload->>'room_id', ''), '!pending_' || cid::text || ':local'),
            COALESCE(NULLIF(payload->>'room_alias', ''), 'conn_' || cid::text),
            (payload->>'created_by_user_id')::uuid,
            COALESCE(NULLIF(payload->>'status', ''), 'provisioning')
        )
        RETURNING * INTO result;

        RETURN to_jsonb(result);

    ELSIF mode = 3 THEN
        SELECT COALESCE(jsonb_agg(row ORDER BY row->>'updated_at' DESC), '[]'::jsonb)
        INTO rows
        FROM (
            SELECT jsonb_build_object(
                'connection_id', uc.id,
                'connection_status', uc.status,
                'user_a_id', uc.user_a_id,
                'user_b_id', uc.user_b_id,
                'connected_at', uc.connected_at,
                'mapping', CASE
                    WHEN m.id IS NULL THEN NULL
                    ELSE jsonb_build_object(
                        'id', m.id,
                        'user_connection_id', m.user_connection_id,
                        'room_id', m.room_id,
                        'room_alias', m.room_alias,
                        'room_type', m.room_type,
                        'status', m.status,
                        'business_context', m.business_context,
                        'created_at', m.created_at,
                        'updated_at', m.updated_at
                    )
                END,
                'peer', jsonb_build_object(
                    'user_id', peer_u.id,
                    'display_name', COALESCE(peer_u.display_name, peer_u.email, 'User'),
                    'email', peer_u.email,
                    'matrix_user_id', peer_mum.mxid
                ),
                'can_chat', (
                    m.status = 'active'
                    AND NOT EXISTS (
                        SELECT 1 FROM user_blocks ub
                        WHERE (ub.blocker_id = uid AND ub.blocked_id = peer_u.id)
                           OR (ub.blocker_id = peer_u.id AND ub.blocked_id = uid)
                    )
                )
            ) AS row
            FROM user_connections uc
            JOIN users peer_u ON peer_u.id = CASE
                WHEN uc.user_a_id = uid THEN uc.user_b_id
                ELSE uc.user_a_id
            END
            LEFT JOIN matrix_room_mappings m ON m.user_connection_id = uc.id
            LEFT JOIN matrix_user_mappings peer_mum ON peer_mum.user_id = peer_u.id
            WHERE uc.status = 'active'
              AND (uc.user_a_id = uid OR uc.user_b_id = uid)
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks ub
                  WHERE (ub.blocker_id = uid AND ub.blocked_id = peer_u.id)
                     OR (ub.blocker_id = peer_u.id AND ub.blocked_id = uid)
              )
              AND (
                  COALESCE((payload->>'include_archived')::boolean, false)
                  OR m.status IS NULL OR m.status <> 'archived'
              )
        ) inbox_rows;

        RETURN rows;

    ELSIF mode = 4 THEN
        UPDATE matrix_room_mappings
        SET
            room_id = COALESCE(NULLIF(payload->>'room_id', ''), room_id),
            room_alias = COALESCE(NULLIF(payload->>'room_alias', ''), room_alias),
            status = COALESCE(NULLIF(payload->>'status', ''), status),
            business_context = COALESCE(payload->'business_context', business_context),
            updated_at = now()
        WHERE user_connection_id = cid
        RETURNING * INTO result;

        IF result.id IS NULL THEN
            RAISE EXCEPTION 'matrix room mapping not found';
        END IF;

        RETURN to_jsonb(result);

    ELSIF mode = 5 THEN
        UPDATE matrix_room_mappings
        SET status = 'archived', updated_at = now()
        WHERE user_connection_id = cid
        RETURNING * INTO result;

        IF result.id IS NULL THEN
            RAISE EXCEPTION 'matrix room mapping not found';
        END IF;

        INSERT INTO matrix_room_archives (room_id, archived_by_user_id, reason)
        VALUES (
            result.room_id,
            NULLIF(payload->>'archived_by_user_id', '')::uuid,
            NULLIF(payload->>'reason', '')
        );

        RETURN to_jsonb(result);

    ELSIF mode = 6 THEN
        UPDATE matrix_room_mappings
        SET status = 'active', updated_at = now()
        WHERE user_connection_id = cid
        RETURNING * INTO result;

        IF result.id IS NULL THEN
            RAISE EXCEPTION 'matrix room mapping not found';
        END IF;

        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_matrix_room_mappings unknown mode: %', mode;
END;
$$;

CREATE OR REPLACE FUNCTION fn_matrix_user_devices(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_user_devices%ROWTYPE;
    rows JSONB;
BEGIN
    IF mode = 1 THEN
        INSERT INTO matrix_user_devices (user_id, device_id, device_label, trust_level, last_seen_at)
        VALUES (
            (payload->>'user_id')::uuid,
            payload->>'device_id',
            NULLIF(payload->>'device_label', ''),
            COALESCE(NULLIF(payload->>'trust_level', ''), 'unknown'),
            NULLIF(payload->>'last_seen_at', '')::timestamptz
        )
        ON CONFLICT (user_id, device_id) DO UPDATE
        SET
            device_label = COALESCE(EXCLUDED.device_label, matrix_user_devices.device_label),
            trust_level = COALESCE(EXCLUDED.trust_level, matrix_user_devices.trust_level),
            last_seen_at = COALESCE(EXCLUDED.last_seen_at, matrix_user_devices.last_seen_at),
            updated_at = now()
        RETURNING * INTO result;
        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(d) ORDER BY d.updated_at DESC), '[]'::jsonb)
        INTO rows
        FROM matrix_user_devices d
        WHERE d.user_id = (payload->>'user_id')::uuid;
        RETURN rows;

    ELSIF mode = 3 THEN
        SELECT * INTO result
        FROM matrix_user_devices
        WHERE user_id = (payload->>'user_id')::uuid
          AND device_id = payload->>'device_id'
        LIMIT 1;
        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 4 THEN
        DELETE FROM matrix_user_devices
        WHERE user_id = (payload->>'user_id')::uuid
          AND device_id = payload->>'device_id'
        RETURNING * INTO result;
        RETURN CASE WHEN result.id IS NULL THEN NULL ELSE to_jsonb(result) END;

    ELSIF mode = 5 THEN
        UPDATE matrix_user_devices
        SET
            trust_level = COALESCE(NULLIF(payload->>'trust_level', ''), 'verified'),
            verified_at = now(),
            updated_at = now()
        WHERE user_id = (payload->>'user_id')::uuid
          AND device_id = payload->>'device_id'
        RETURNING * INTO result;
        IF result.id IS NULL THEN
            RAISE EXCEPTION 'matrix device not found';
        END IF;
        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_matrix_user_devices unknown mode: %', mode;
END;
$$;

CREATE OR REPLACE FUNCTION fn_matrix_attachment_metadata(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_attachment_metadata%ROWTYPE;
    rows JSONB;
BEGIN
    IF mode = 1 THEN
        INSERT INTO matrix_attachment_metadata (
            room_id, event_id, mimetype, size_bytes, sha256,
            thumbnail_event_id, uploaded_by_user_id
        )
        VALUES (
            payload->>'room_id',
            payload->>'event_id',
            NULLIF(payload->>'mimetype', ''),
            NULLIF(payload->>'size_bytes', '')::bigint,
            NULLIF(payload->>'sha256', ''),
            NULLIF(payload->>'thumbnail_event_id', ''),
            NULLIF(payload->>'uploaded_by_user_id', '')::uuid
        )
        ON CONFLICT (room_id, event_id) DO UPDATE
        SET
            mimetype = COALESCE(EXCLUDED.mimetype, matrix_attachment_metadata.mimetype),
            size_bytes = COALESCE(EXCLUDED.size_bytes, matrix_attachment_metadata.size_bytes),
            sha256 = COALESCE(EXCLUDED.sha256, matrix_attachment_metadata.sha256),
            thumbnail_event_id = COALESCE(
                EXCLUDED.thumbnail_event_id,
                matrix_attachment_metadata.thumbnail_event_id
            )
        WHERE matrix_attachment_metadata.uploaded_by_user_id = EXCLUDED.uploaded_by_user_id
        RETURNING * INTO result;
        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(a) ORDER BY a.created_at DESC), '[]'::jsonb)
        INTO rows
        FROM matrix_attachment_metadata a
        WHERE a.room_id = payload->>'room_id';
        RETURN rows;

    ELSIF mode = 3 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(a) ORDER BY a.created_at DESC), '[]'::jsonb) INTO rows
        FROM matrix_attachment_metadata a
        JOIN matrix_room_mappings m ON m.room_id=a.room_id
        JOIN user_connections c ON c.id=m.user_connection_id
        WHERE (payload->>'user_id')::uuid IN (c.user_a_id,c.user_b_id)
        AND c.status='active' AND m.status IN ('invited','joined','active')
        AND NOT EXISTS (SELECT 1 FROM user_blocks b WHERE
          (b.blocker_id=c.user_a_id AND b.blocked_id=c.user_b_id) OR
          (b.blocker_id=c.user_b_id AND b.blocked_id=c.user_a_id))
        AND (NULLIF(payload->>'room_id','') IS NULL OR a.room_id=payload->>'room_id')
        AND (NULLIF(payload->>'mimetype','') IS NULL OR a.mimetype=payload->>'mimetype');

        RETURN rows;
    END IF;

    RAISE EXCEPTION 'fn_matrix_attachment_metadata unknown mode: %', mode;
END;
$$;

CREATE OR REPLACE FUNCTION fn_matrix_business_events(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_business_events%ROWTYPE;
    rows JSONB;
BEGIN
    IF mode = 1 THEN
        INSERT INTO matrix_business_events (
            room_id, event_id, event_type, aggregate_id, payload_hash
        )
        VALUES (
            payload->>'room_id',
            payload->>'event_id',
            payload->>'event_type',
            NULLIF(payload->>'aggregate_id', ''),
            payload->>'payload_hash'
        )
        ON CONFLICT (room_id, event_id) DO NOTHING
        RETURNING * INTO result;
        IF result.id IS NULL THEN
            SELECT * INTO result
            FROM matrix_business_events
            WHERE room_id = payload->>'room_id'
              AND event_id = payload->>'event_id'
            LIMIT 1;
        END IF;
        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(e) ORDER BY e.published_at DESC), '[]'::jsonb)
        INTO rows
        FROM matrix_business_events e
        WHERE e.room_id = payload->>'room_id';
        RETURN rows;
    END IF;

    RAISE EXCEPTION 'fn_matrix_business_events unknown mode: %', mode;
END;
$$;

CREATE OR REPLACE FUNCTION fn_matrix_notification_preferences(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_notification_preferences%ROWTYPE;
BEGIN
    IF mode = 1 THEN
        INSERT INTO matrix_notification_preferences (user_id)
        VALUES ((payload->>'user_id')::uuid)
        ON CONFLICT (user_id) DO NOTHING;

        UPDATE matrix_notification_preferences
        SET
            mentions_enabled = COALESCE((payload->>'mentions_enabled')::boolean, mentions_enabled),
            invites_enabled = COALESCE((payload->>'invites_enabled')::boolean, invites_enabled),
            messages_enabled = COALESCE((payload->>'messages_enabled')::boolean, messages_enabled),
            business_events_enabled = COALESCE(
                (payload->>'business_events_enabled')::boolean,
                business_events_enabled
            ),
            quiet_hours_start = COALESCE(
                NULLIF(payload->>'quiet_hours_start', '')::time,
                quiet_hours_start
            ),
            quiet_hours_end = COALESCE(
                NULLIF(payload->>'quiet_hours_end', '')::time,
                quiet_hours_end
            ),
            updated_at = now()
        WHERE user_id = (payload->>'user_id')::uuid
        RETURNING * INTO result;
        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT * INTO result
        FROM matrix_notification_preferences
        WHERE user_id = (payload->>'user_id')::uuid
        LIMIT 1;
        IF result.user_id IS NULL THEN
            INSERT INTO matrix_notification_preferences (user_id)
            VALUES ((payload->>'user_id')::uuid)
            RETURNING * INTO result;
        END IF;
        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_matrix_notification_preferences unknown mode: %', mode;
END;
$$;

CREATE OR REPLACE FUNCTION fn_matrix_key_backup_metadata(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_key_backup_metadata%ROWTYPE;
    rows JSONB;
BEGIN
    IF mode = 1 THEN
        INSERT INTO matrix_key_backup_metadata (user_id, backup_version, algorithm)
        VALUES (
            (payload->>'user_id')::uuid,
            payload->>'backup_version',
            COALESCE(NULLIF(payload->>'algorithm', ''), 'm.megolm_backup.v1')
        )
        ON CONFLICT (user_id, backup_version) DO UPDATE
        SET algorithm = EXCLUDED.algorithm
        RETURNING * INTO result;
        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT COALESCE(jsonb_agg(to_jsonb(k) ORDER BY k.created_at DESC), '[]'::jsonb)
        INTO rows
        FROM matrix_key_backup_metadata k
        WHERE k.user_id = (payload->>'user_id')::uuid;
        RETURN rows;
    END IF;

    RAISE EXCEPTION 'fn_matrix_key_backup_metadata unknown mode: %', mode;
END;
$$;

CREATE OR REPLACE FUNCTION fn_matrix_room_settings(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_room_settings%ROWTYPE;
BEGIN
    IF mode = 1 THEN
        INSERT INTO matrix_room_settings (room_id)
        VALUES (payload->>'room_id')
        ON CONFLICT (room_id) DO NOTHING;

        UPDATE matrix_room_settings
        SET
            pinned_event_ids = COALESCE(payload->'pinned_event_ids', pinned_event_ids),
            muted = COALESCE((payload->>'muted')::boolean, muted),
            retention_policy = COALESCE(NULLIF(payload->>'retention_policy', ''), retention_policy),
            metadata = COALESCE(payload->'metadata', metadata),
            updated_at = now()
        WHERE room_id = payload->>'room_id'
        RETURNING * INTO result;
        RETURN to_jsonb(result);

    ELSIF mode = 2 THEN
        SELECT * INTO result
        FROM matrix_room_settings
        WHERE room_id = payload->>'room_id'
        LIMIT 1;
        RETURN CASE WHEN result.room_id IS NULL THEN NULL ELSE to_jsonb(result) END;
    END IF;

    RAISE EXCEPTION 'fn_matrix_room_settings unknown mode: %', mode;
END;
$$;

CREATE OR REPLACE FUNCTION fn_matrix_reports(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_reports%ROWTYPE;
BEGIN
    IF mode = 1 THEN
        INSERT INTO matrix_reports (report_id, room_id, event_id)
        VALUES (
            (payload->>'report_id')::uuid,
            NULLIF(payload->>'room_id', ''),
            NULLIF(payload->>'event_id', '')
        )
        RETURNING * INTO result;
        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_matrix_reports unknown mode: %', mode;
END;
$$;
