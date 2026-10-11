"""Prepare only the isolated Matrix test database; never targets application data."""

import asyncio
import os
import sys

import asyncpg


async def main() -> None:
    dsn = os.environ.get(
        "MATRIX_TEST_DATABASE_URL",
        "postgresql://matrix_test:matrix-test-only@127.0.0.1:15439/matrix_test",
    )
    from urllib.parse import urlparse

    parsed = urlparse(dsn)
    if parsed.hostname != "127.0.0.1" or parsed.port != 15439 or parsed.path != "/matrix_test":
        raise RuntimeError("Only the isolated matrix_test database on port 15439 is permitted")
    conn = await asyncpg.connect(dsn)
    try:
        mode = sys.argv[1]
        if mode in {"pause", "unpause"}:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "compose",
                "-f",
                "/tmp/paripath-matrix-integration/compose.yaml",
                mode,
                "synapse",
                stdout=asyncio.subprocess.DEVNULL,
            )
            if await process.wait() != 0:
                raise RuntimeError("Isolated service fault injection failed")
            print("ok")
            return
        if mode == "fail-local":
            await conn.execute("""CREATE OR REPLACE FUNCTION matrix_test_fail_revocation()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.payload->>'scope' IN ('current','all') THEN
            RAISE EXCEPTION 'isolated injected revocation failure'; END IF; RETURN NEW; END $$;
            CREATE TRIGGER matrix_test_fail_revocation BEFORE INSERT ON auth_remote_operations
            FOR EACH ROW EXECUTE FUNCTION matrix_test_fail_revocation();""")
            print("ok")
            return
        if mode == "restore-local":
            await conn.execute(
                "DROP TRIGGER IF EXISTS matrix_test_fail_revocation ON auth_remote_operations; "
                "DROP FUNCTION IF EXISTS matrix_test_fail_revocation();"
            )
            print("ok")
            return
        if mode != "connection":
            raise ValueError("Unsupported isolated fixture operation")
        users = await conn.fetch(
            "SELECT id FROM users WHERE email IN ('alice@example.com','bob@example.com') "
            "ORDER BY email"
        )
        if len(users) != 2:
            raise RuntimeError("Both test users must complete hosted authentication first")
        ordered = sorted((users[0]["id"], users[1]["id"]))
        existing = await conn.fetchval(
            "SELECT id FROM user_connections WHERE user_a_id=$1 AND user_b_id=$2 LIMIT 1",
            *ordered,
        )
        cid = existing or await conn.fetchval(
            "INSERT INTO user_connections(user_a_id,user_b_id) VALUES($1,$2) RETURNING id",
            *ordered,
        )
        await conn.execute(
            "SELECT fn_matrix_room_mappings(2,jsonb_build_object('user_connection_id',$1::text,"
            "'created_by_user_id',$2::text))",
            str(cid),
            str(users[0]["id"]),
        )
        print(cid)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
