-- Tinode chat functions (authoritative fn_tinode_conversation_mappings).

CREATE OR REPLACE FUNCTION fn_tinode_conversation_mappings(mode INT, payload JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result tinode_conversation_mappings%ROWTYPE;
    cid UUID;
    uid UUID;
    rows JSONB;
BEGIN
    cid := (payload->>'user_connection_id')::uuid;
    uid := (payload->>'user_id')::uuid;

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

        INSERT INTO tinode_conversation_mappings (
            user_connection_id,
            tinode_topic_id,
            tinode_topic_name,
            created_by_user_id,
            status
        )
        VALUES (
            cid,
            'pp_conn_' || cid::text,
            'pp_conn_' || cid::text,
            (payload->>'created_by_user_id')::uuid,
            'provisioning'
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
                        'tinode_topic_id', m.tinode_topic_id,
                        'tinode_topic_name', m.tinode_topic_name,
                        'status', m.status,
                        'created_at', m.created_at,
                        'updated_at', m.updated_at
                    )
                END,
                'peer', jsonb_build_object(
                    'user_id', peer_u.id,
                    'display_name', COALESCE(peer_u.display_name, peer_u.email, 'User'),
                    'email', peer_u.email,
                    'tinode_user_id', peer_tum.tinode_user_id
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
            LEFT JOIN tinode_conversation_mappings m ON m.user_connection_id = uc.id
            LEFT JOIN tinode_user_mappings peer_tum ON peer_tum.user_id = peer_u.id
            WHERE uc.status = 'active'
              AND (uc.user_a_id = uid OR uc.user_b_id = uid)
              AND NOT EXISTS (
                  SELECT 1 FROM user_blocks ub
                  WHERE (ub.blocker_id = uid AND ub.blocked_id = peer_u.id)
                     OR (ub.blocker_id = peer_u.id AND ub.blocked_id = uid)
              )
              AND COALESCE((payload->>'include_archived')::boolean, false)
                  OR m.status IS NULL OR m.status <> 'archived'
        ) inbox_rows;

        RETURN rows;

    ELSIF mode = 4 THEN
        UPDATE tinode_conversation_mappings
        SET
            tinode_topic_id = COALESCE(NULLIF(payload->>'tinode_topic_id', ''), tinode_topic_id),
            tinode_topic_name = COALESCE(NULLIF(payload->>'tinode_topic_name', ''), tinode_topic_name),
            status = COALESCE(NULLIF(payload->>'status', ''), status),
            updated_at = now()
        WHERE user_connection_id = cid
        RETURNING * INTO result;

        IF result.id IS NULL THEN
            RAISE EXCEPTION 'conversation mapping not found';
        END IF;

        RETURN to_jsonb(result);

    ELSIF mode = 5 THEN
        UPDATE tinode_conversation_mappings
        SET status = 'archived', updated_at = now()
        WHERE user_connection_id = cid
        RETURNING * INTO result;

        IF result.id IS NULL THEN
            RAISE EXCEPTION 'conversation mapping not found';
        END IF;

        RETURN to_jsonb(result);

    END IF;

    RAISE EXCEPTION 'fn_tinode_conversation_mappings unknown mode: %', mode;
END;
$$;
