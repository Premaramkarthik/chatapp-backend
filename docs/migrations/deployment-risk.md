# Production Deployment Risk Assessment

**Change:** Replace 15 legacy SQL migration files with 7 consolidated files.  
**Risk level:** **HIGH** for existing environments with `schema_migrations` history; **LOW** for greenfield installs.

## Risk Summary

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Checksum mismatch on re-run | High | Certain if old rows exist | Do not re-apply; baseline or new DB only |
| Missing `015_delete_user` on prod | Medium | Observed on local `chatapp` DB | Deploy consolidated `003_functions_core.sql` logic includes mode 14; verify `fn_users` body |
| Filename drift in CI/CD | Medium | Possible | Update deploy scripts/docs to expect 7 files |
| Schema drift undetected | Medium | Low if validated | Compare `pg_dump --schema-only` before/after on staging |
| Downtime during transition | Low | N/A for file-only change | No migration run needed if schema already current |

## Migration Runner Behavior

`scripts/run_migrations.py`:

1. Sorts `migrations/*.sql` by filename
2. Skips files already in `schema_migrations` with matching checksum
3. **Raises `RuntimeError`** if filename exists but checksum changed

**Implication:** Deploying consolidated files to a database that recorded `001_create_core_tables.sql` etc. will **not** auto-apply new files — new filenames are treated as pending. That is safe (won't double-create tables) but may leave `schema_migrations` inconsistent with repo.

**Implication:** Modifying an already-applied legacy file checksum would **halt** deploy — consolidated refactor avoids this by using new filenames.

## Observed Local State

`chatapp` database at audit time:

- 14 legacy migrations recorded (001–014)
- `015_delete_user.sql` **not** applied → `fn_users` mode 14 missing in dev until manual apply or consolidated redeploy

## Recommended Production Paths

### Path 1: Greenfield / new region

1. Deploy application + consolidated `migrations/`
2. Run `uv run python scripts/run_migrations.py`
3. Verify health endpoint and auth signup smoke tests

### Path 2: Existing production (schema current via legacy chain)

1. **Do not** run consolidated migrations on live DB
2. Verify `fn_users` includes modes 13–14 (compare `pg_get_functiondef` or integration test account deletion)
3. If mode 14 missing, apply **only** the `fn_users` body via controlled SQL window (or one-time ops script), not full re-migration
4. Optionally insert consolidated filenames into `schema_migrations` after checksum audit on staging clone

### Path 3: Staging re-baseline (pre-prod validation)

1. Clone production → staging
2. `pg_dump --schema-only` before
3. Fresh DB + consolidated migrations → `pg_dump --schema-only` after
4. `diff` schemas (ignore extension noise)
5. Run application integration tests

## Pre-Deploy Checklist

- [ ] Confirm target DB migration history (`SELECT * FROM schema_migrations`)
- [ ] Confirm whether `fn_users` mode 14 exists in production
- [ ] Backup database
- [ ] Run consolidated chain on empty staging DB and diff schema
- [ ] Update runbooks referencing `001–010` or `015_delete_user.sql`
- [ ] Communicate dev-team need to re-baseline local DBs

## Post-Deploy Verification

- `GET /v1/health` returns OK
- Signup → verify email → onboarding flow (modes 10, 13)
- Account deletion API (mode 14) if enabled
- Connection accept + chat provision (modes 2–4 on `fn_tinode_conversation_mappings`)

## Rollback Plan

- **Application rollback:** redeploy previous container image
- **Schema rollback:** restore DB snapshot; forward-only migrations cannot be reversed in-runner
- **Partial hotfix:** restore prior `fn_users` / `fn_tinode_conversation_mappings` from git tag via `CREATE OR REPLACE`
