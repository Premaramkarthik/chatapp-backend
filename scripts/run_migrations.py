"""Run idempotent SQL migrations from the migrations directory."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config.settings import settings  # noqa: E402

MIGRATIONS_DIR = REPO_ROOT / "migrations"

SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@dataclass(frozen=True)
class MigrationResult:
    """Result for one migration file."""

    filename: str
    status: str


@dataclass(frozen=True)
class MigrationFile:
    """Loaded migration file content."""

    filename: str
    checksum: str
    sql: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run chatapp SQL migrations")
    parser.add_argument("--database-url", default=None, help="Override DB DSN")
    parser.add_argument(
        "--migrations-dir",
        default=str(MIGRATIONS_DIR),
        help="SQL migration folder",
    )
    parser.add_argument(
        "--repair-changed",
        action="store_true",
        help="Re-apply migrations whose checksum changed since last apply (dev only)",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    dsn = args.database_url or settings.database.direct_dsn
    migrations_dir = Path(args.migrations_dir)
    results = await run_migrations(
        dsn,
        migrations_dir,
        repair_changed=args.repair_changed,
    )
    for result in results:
        print(f"{result.status}: {result.filename}")
    return 0


async def run_migrations(
    dsn: str,
    migrations_dir: Path = MIGRATIONS_DIR,
    *,
    repair_changed: bool = False,
) -> list[MigrationResult]:
    """Apply unapplied SQL files in filename order."""
    if repair_changed and settings.app.environment not in {"local", "development", "dev", "test"}:
        raise RuntimeError("--repair-changed is restricted to local/development databases")
    migration_files = await asyncio.to_thread(_load_migration_files, migrations_dir)
    conn = await asyncpg.connect(dsn=dsn)
    try:
        await conn.execute("SELECT pg_advisory_lock(734921001)")
        await conn.execute(SCHEMA_MIGRATIONS_SQL)
        results: list[MigrationResult] = []
        for migration in migration_files:
            row = await conn.fetchrow(
                "SELECT checksum FROM schema_migrations WHERE filename = $1",
                migration.filename,
            )
            if row is not None:
                if row["checksum"] != migration.checksum:
                    if not repair_changed:
                        raise RuntimeError(
                            f"Migration checksum changed after apply: {migration.filename}. "
                            "Re-run with --repair-changed to re-apply (dev only)."
                        )
                    async with conn.transaction():
                        await conn.execute(migration.sql)
                        await conn.execute(
                            """
                            UPDATE schema_migrations
                            SET checksum = $2, applied_at = now()
                            WHERE filename = $1
                            """,
                            migration.filename,
                            migration.checksum,
                        )
                    results.append(MigrationResult(filename=migration.filename, status="repaired"))
                    continue
                results.append(MigrationResult(filename=migration.filename, status="skipped"))
                continue

            async with conn.transaction():
                await conn.execute(migration.sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2)",
                    migration.filename,
                    migration.checksum,
                )
            results.append(MigrationResult(filename=migration.filename, status="applied"))
        return results
    finally:
        await conn.close()


def _load_migration_files(migrations_dir: Path) -> list[MigrationFile]:
    paths = sorted(migrations_dir.glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in paths]
    if len(set(versions)) != len(versions) or any(not v.isdigit() for v in versions):
        raise RuntimeError("Migration versions must be unique numeric prefixes")
    return [
        MigrationFile(
            filename=path.name,
            checksum=_checksum(path),
            sql=path.read_text(encoding="utf-8"),
        )
        for path in paths
    ]


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
