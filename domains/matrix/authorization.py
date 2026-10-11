"""Local authorization for Matrix room metadata; deny without an active unblocked connection."""

from fastapi import HTTPException

from infrastructure.database.connection import fetchrow


async def require_room_access(user_id: str, room_id: str) -> None:
    row = await fetchrow(
        """SELECT m.room_id FROM matrix_room_mappings m
    JOIN user_connections c ON c.id=m.user_connection_id
    WHERE m.room_id=$2 AND c.status='active' AND $1::uuid IN (c.user_a_id,c.user_b_id)
    AND m.status IN ('invited','joined','active') AND NOT EXISTS (
      SELECT 1 FROM user_blocks b WHERE (b.blocker_id=c.user_a_id AND b.blocked_id=c.user_b_id)
      OR (b.blocker_id=c.user_b_id AND b.blocked_id=c.user_a_id))""",
        user_id,
        room_id,
    )
    if not row:
        raise HTTPException(403, detail={"code": "matrix_room_access_denied"})
