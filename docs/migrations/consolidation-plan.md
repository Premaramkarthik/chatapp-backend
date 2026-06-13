# Migration Consolidation Plan

## Goal

Single authoritative definition per database object, deterministic fresh-install path, preserved final schema expected by the Python application layer.

## Target File Layout

| # | File | Layer | Contents |
|---|------|-------|----------|
| 001 | `001_extensions.sql` | Extensions | `pgcrypto`, `pg_trgm` |
| 002 | `002_tables.sql` | Tables + indexes + constraints | 23 tables, all indexes, idempotent `DO $$` constraint adds |
| 003 | `003_functions_core.sql` | Functions | `set_updated_at`, `fn_health`, `fn_tinode_user_mappings`, `fn_signup_sessions`, **`fn_users` (modes 1–14)** |
| 004 | `004_functions_social.sql` | Functions | `social_*` helpers, discovery/connection/profile/travel/outbox `fn_*` |
| 005 | `005_functions_chat.sql` | Functions | **`fn_tinode_conversation_mappings` (modes 1–5)** |
| 006 | `006_triggers.sql` | Triggers | 10 `updated_at` triggers |
| 007 | `007_seeds_geo.sql` | Seeds | 10 countries, 13 cities |

**Skipped layers (not applicable):** enums, views, stored procedures.

## Legacy → Consolidated Mapping

| Legacy file(s) | Consolidated into |
|----------------|-------------------|
| `001_create_core_tables.sql` | `002_tables.sql` (users, tinode_user_mappings) |
| `002_create_core_functions.sql` | `003_functions_core.sql` (minus old `fn_users`), `006_triggers.sql` |
| `003_create_auth_tables.sql` | `002_tables.sql`, `003_functions_core.sql` (partial `fn_users` dropped) |
| `004_create_signup_lifecycle.sql` | `002_tables.sql`, `003_functions_core.sql` |
| `005_geo_reference.sql` | `001_extensions.sql` (pg_trgm), `002_tables.sql`, `007_seeds_geo.sql` |
| `006_explorer_connector_profiles.sql` | `002_tables.sql`, `006_triggers.sql` |
| `007_travel_plans.sql` | `002_tables.sql`, `006_triggers.sql` |
| `008_discovery_connections.sql` | `002_tables.sql`, `006_triggers.sql` |
| `009_tinode_conversations.sql` | `002_tables.sql`, `006_triggers.sql` |
| `010_search_outbox.sql` | `002_tables.sql` |
| `011_create_social_functions.sql` | `004_functions_social.sql` (chat fn removed) |
| `012_tinode_chat_functions.sql` | `005_functions_chat.sql` |
| `013_onboarding_flow.sql` | `003_functions_core.sql` (`fn_users` mode 13) |
| `014_activate_pending_by_email.sql` | `003_functions_core.sql` (modes 8, 10 email fallback) |
| `015_delete_user.sql` | `003_functions_core.sql` (mode 14) |

## Authoritative Function Versions

### `fn_users` (from `015_delete_user.sql`)

- Modes 1–14 including onboarding (13), email-based activation fallback (10), Keycloak sub relink (8), delete by sub (14).
- Mode 12 still targets `pending_verification`; mode 13 targets `pending_profile_setup`.

### `fn_tinode_conversation_mappings` (from `012_tinode_chat_functions.sql`)

- Mode 2 provisions with `status = 'provisioning'` (not `active`).
- Modes 3–5: inbox list, update mapping, archive.

## Idempotency Strategy

| Pattern | Usage |
|---------|-------|
| `CREATE EXTENSION IF NOT EXISTS` | extensions |
| `CREATE TABLE IF NOT EXISTS` | tables (full final column set) |
| `CREATE INDEX IF NOT EXISTS` | indexes |
| `DO $$ … IF NOT EXISTS (pg_constraint)` | constraints |
| `CREATE OR REPLACE FUNCTION` | functions |
| `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER` | triggers |
| `INSERT … ON CONFLICT DO NOTHING` | seeds |

## Existing Database Transition

The migration runner (`scripts/run_migrations.py`) tracks applied files by **filename + SHA-256 checksum**. Renaming or replacing files breaks checksum continuity for databases that already applied legacy filenames.

### Dev database (has legacy `schema_migrations` rows)

**Option A — Re-baseline (recommended for local dev)**

```sql
-- As superuser, after backing up data if needed
DROP DATABASE chatapp;
CREATE DATABASE chatapp OWNER chatapp;
-- Then run: uv run python scripts/run_migrations.py
```

**Option B — Manual baseline record (schema already matches final state)**

Only if you have verified the live schema matches post-consolidation expectations:

```sql
-- Insert new filenames with checksums from a fresh run, OR
-- Truncate and re-insert after running against empty DB
TRUNCATE schema_migrations;
```

**Option C — Keep legacy history, do not re-run**

Do not execute consolidated files against a DB that already has the final schema from legacy migrations 001–014. Application continues to work; only **new** environments use consolidated files.

### Production

See [deployment-risk.md](./deployment-risk.md). Do **not** blindly re-run migrations on production after this refactor.

## Validation Checklist

- [x] Fresh database: all 7 files apply without error
- [x] Second run: all files `skipped` (checksum match)
- [x] 23 public tables present
- [x] 15 `fn_*` application functions present
- [x] 10 `updated_at` triggers present
- [x] Geo seeds: 10 countries, 13 cities
- [x] Smoke: `fn_health(1)`, `fn_users(7)` on test DB
- [x] `tests/test_migrations.py` passes

## Rollback Approach

Migrations are **forward-only**. No down migrations are maintained.

| Scenario | Approach |
|----------|----------|
| Failed mid-apply on empty DB | `DROP DATABASE` / recreate and re-run |
| Bad deploy on populated DB | Restore PostgreSQL snapshot / PITR |
| Function regression | `CREATE OR REPLACE` hotfix migration or restore previous function body from git history |

Rollback validation: not executed against production data. Documented approach only — see [validation-results.md](./validation-results.md).
