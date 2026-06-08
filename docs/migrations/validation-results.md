# Fresh-Install and Rollback Validation Results

**Date:** 2026-06-06  
**Environment:** PostgreSQL 17 (`chatapp-backend-postgres-1`, port 5433)

## Fresh-Install Validation

### Procedure

```bash
# Superuser creates isolated database
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d postgres \
  -c "DROP DATABASE IF EXISTS chatapp_migration_test;" \
  -c "CREATE DATABASE chatapp_migration_test OWNER chatapp;"

# Apply consolidated migrations
cd /home/karthik/Downloads/chatapp-backend
uv run python scripts/run_migrations.py \
  --database-url "postgresql://chatapp:chatapp@localhost:5433/chatapp_migration_test"
```

### First Run Result

| File | Status |
|------|--------|
| `001_extensions.sql` | applied |
| `002_tables.sql` | applied |
| `003_functions_core.sql` | applied |
| `004_functions_social.sql` | applied |
| `005_functions_chat.sql` | applied |
| `006_triggers.sql` | applied |
| `007_seeds_geo.sql` | applied |

**Outcome:** PASS — no errors.

### Idempotency Re-Run

Second execution: all 7 files **skipped** (checksum match).

**Outcome:** PASS

### Object Counts

| Object type | Count |
|-------------|-------|
| Public tables | 24 (23 app + `schema_migrations`) |
| Application `fn_*` functions | 15 |
| `updated_at` triggers | 10 |
| Extensions (`pgcrypto`, `pg_trgm`) | 2 |
| Seed countries | 10 |
| Seed cities | 13 |

### Smoke Tests

```sql
SELECT fn_health(1, '{}');
-- {"ok": true, "database_time": "..."}

SELECT (fn_users(7, '{"email":"test@example.com","created_via":"email"}'::jsonb))->>'status';
-- pending_verification
```

**Outcome:** PASS

### Unit Tests

```
uv run pytest tests/test_migrations.py -q
# 1 passed
```

**Outcome:** PASS

## Rollback Validation

**Status:** Approach documented; automated down-migration **not implemented** (by design).

| Test | Result |
|------|--------|
| Down migration scripts exist | N/A — not in project scope |
| `DROP DATABASE` + re-apply | PASS (used for fresh-install test) |
| PITR / snapshot restore | Not tested (ops procedure) |
| `CREATE OR REPLACE` function hotfix | Supported — standard PostgreSQL |

### Recommended Rollback Procedure

1. Stop API traffic to affected services
2. Restore PostgreSQL from last known-good snapshot
3. Redeploy previous application artifact if needed
4. Verify `schema_migrations` row count matches expected legacy or consolidated set

## Comparison with Existing Dev DB

Local `chatapp` database retains **14 legacy** `schema_migrations` entries (001–014). Consolidated filenames are disjoint — runner will attempt to apply 001–007 consolidated files if executed against `chatapp` without baseline cleanup.

**Warning:** Running consolidated migrations against a fully-migrated legacy `chatapp` DB may fail on constraint/index "already exists" unless tables were created with identical definitions. Treat as **re-baseline only** for dev.

## Assumptions

1. PostgreSQL 15+ (`EXECUTE FUNCTION` trigger syntax) — project uses PG 17
2. `users_email_key` UNIQUE + `idx_users_email_unique` coexist for `ON CONFLICT (email)` and case-insensitive lookup
3. Production schema matches legacy chain through **014**; **015** was never applied locally
