-- Per-user inbox archive (viewer preference) decoupled from shared mapping lifecycle.

CREATE TABLE IF NOT EXISTS matrix_inbox_archive (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_connection_id UUID NOT NULL REFERENCES user_connections(id) ON DELETE CASCADE,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, user_connection_id)
);

CREATE INDEX IF NOT EXISTS idx_matrix_inbox_archive_connection
    ON matrix_inbox_archive (user_connection_id);

-- Migrate legacy shared archived mappings to per-user rows for both connection members.
INSERT INTO matrix_inbox_archive (user_id, user_connection_id, archived_at)
SELECT uc.user_a_id, m.user_connection_id, COALESCE(m.updated_at, now())
FROM matrix_room_mappings m
JOIN user_connections uc ON uc.id = m.user_connection_id
WHERE m.status = 'archived'
ON CONFLICT (user_id, user_connection_id) DO NOTHING;

INSERT INTO matrix_inbox_archive (user_id, user_connection_id, archived_at)
SELECT uc.user_b_id, m.user_connection_id, COALESCE(m.updated_at, now())
FROM matrix_room_mappings m
JOIN user_connections uc ON uc.id = m.user_connection_id
WHERE m.status = 'archived'
ON CONFLICT (user_id, user_connection_id) DO NOTHING;

UPDATE matrix_room_mappings
SET status = 'active', updated_at = now()
WHERE status = 'archived'
  AND room_id LIKE '!%';

CREATE OR REPLACE FUNCTION fn_matrix_room_mappings(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result matrix_room_mappings%ROWTYPE;
    cid UUID;
    uid UUID;
    rows JSONB;
    inbox_status TEXT;
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
        inbox_status := COALESCE(NULLIF(payload->>'status', ''), 'active');

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
                'is_user_archived', EXISTS (
                    SELECT 1 FROM matrix_inbox_archive ia
                    WHERE ia.user_id = uid
                      AND ia.user_connection_id = uc.id
                ),
                'can_chat', (
                    m.status = 'active'
                    AND m.room_id LIKE '!%'
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
                  inbox_status = 'all'
                  OR (
                      inbox_status = 'active'
                      AND NOT EXISTS (
                          SELECT 1 FROM matrix_inbox_archive ia
                          WHERE ia.user_id = uid
                            AND ia.user_connection_id = uc.id
                      )
                  )
                  OR (
                      inbox_status = 'archived'
                      AND EXISTS (
                          SELECT 1 FROM matrix_inbox_archive ia
                          WHERE ia.user_id = uid
                            AND ia.user_connection_id = uc.id
                      )
                  )
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
        SELECT * INTO result
        FROM matrix_room_mappings
        WHERE user_connection_id = cid;

        IF result.id IS NULL THEN
            RAISE EXCEPTION 'matrix room mapping not found';
        END IF;

        IF uid IS NULL THEN
            RAISE EXCEPTION 'user_id required for per-user archive';
        END IF;

        INSERT INTO matrix_inbox_archive (user_id, user_connection_id)
        VALUES (uid, cid)
        ON CONFLICT (user_id, user_connection_id) DO UPDATE
            SET archived_at = now();

        INSERT INTO matrix_room_archives (room_id, archived_by_user_id, reason)
        VALUES (
            result.room_id,
            uid,
            NULLIF(payload->>'reason', '')
        );

        RETURN to_jsonb(result);

    ELSIF mode = 6 THEN
        SELECT * INTO result
        FROM matrix_room_mappings
        WHERE user_connection_id = cid;

        IF result.id IS NULL THEN
            RAISE EXCEPTION 'matrix room mapping not found';
        END IF;

        IF uid IS NULL THEN
            RAISE EXCEPTION 'user_id required for per-user reopen';
        END IF;

        DELETE FROM matrix_inbox_archive
        WHERE user_id = uid
          AND user_connection_id = cid;

        RETURN to_jsonb(result);
    END IF;

    RAISE EXCEPTION 'fn_matrix_room_mappings unknown mode: %', mode;
END;
$$;
