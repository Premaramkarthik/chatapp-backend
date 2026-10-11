# Role Migration Plan — Traveler/Messenger → Explorer/Connector

This document records the backend migration from legacy role terminology to the Explorer/Connector domain model.

## Goals

- Replace `account_mode` values: `traveler` → `explorer`, `messenger` → `connector`
- Remove legacy terms from API paths, SQL functions, tables, Python modules, and docs
- Preserve capability-based authorization (`trip:create`, `trip:join`) unchanged

## Database changes

### Data migration (`011_explorer_connector_role_migration.sql`)

| Table / column | Change |
| --- | --- |
| `users.account_mode` | `traveler` → `explorer`, `messenger` → `connector` |
| `oauth_signin_states.account_mode` | Same value mapping |
| `users_account_mode_check` | Allowed values: `explorer`, `connector` |

### Table renames

| Legacy | New |
| --- | --- |
| `traveler_profiles` | `explorer_profiles` |
| `messenger_profiles` | `connector_profiles` |
| `traveler_current_locations` | `explorer_current_locations` |
| `traveler_discovery_snapshots` | `explorer_discovery_snapshots` |

Renames are conditional in migration 009 so fresh installs (already on new names from `002_tables.sql`) skip safely.

### Function renames

| Legacy | New |
| --- | --- |
| `fn_traveler_profiles` | `fn_explorer_profiles` |
| `fn_messenger_profiles` | `fn_connector_profiles` |
| `fn_traveler_current_locations` | `fn_explorer_current_locations` |

`social_rebuild_discovery_snapshot` now requires `account_mode = 'explorer'` for discoverability.

### Outbox / search

- `search_outbox_events.aggregate_type` default: `explorer_discovery_snapshot`
- Existing rows updated from `traveler_discovery_snapshot`

## API changes (breaking)

| Legacy | New |
| --- | --- |
| `GET/PUT /v1/travelers/profile` | `GET/PUT /v1/explorers/profile` |
| `POST /v1/travelers/trips` | `POST /v1/explorers/trips` |
| `PUT /v1/travelers/location` | `PUT /v1/explorers/location` |
| `GET /v1/travelers/search` | `GET /v1/explorers/search` |
| `account_mode: "traveler"` | `account_mode: "explorer"` |
| `account_mode: "messenger"` | `account_mode: "connector"` |

OpenAPI tag: `explorers` (was `travelers`).

Response schema renames: `ExplorerProfileResponse`, `ExplorerSearchResponse`, etc.

## Search index (Typesense)

| Legacy | New |
| --- | --- |
| Legacy explorer search index | Typesense `travelers` collection |
| Legacy search env vars | `TYPESENSE_*` + `SEARCH_CACHE_TTL_*` |

Re-index with `scripts/rebuild_search_index.py` after deploy. Outbox + Dramatiq workers sync snapshots asynchronously.

## Frontend coordination

The ConnectCarry frontend must update in the same release (or immediately after backend deploy):

1. **API base paths** — `/v1/travelers/*` → `/v1/explorers/*`
2. **Account mode strings** — `traveler`/`messenger` → `explorer`/`connector` in onboarding, settings, session handling
3. **BFF client** — rename `travelers` module to `explorers` (e.g. `src/lib/api/travelers.ts`)
4. **Routes** — `/traveler`, `/messenger` app routes (if present) should align with product naming
5. **Role selection UI** — copy and enum values for Explorer vs Connector

Capabilities in JWT remain `trip:create` (explorer) and `trip:join` (connector); Keycloak role mapping does not need to change unless role display names are updated separately.

## Migration strategy

1. Deploy backend with migration `009` applied (`python scripts/run_migrations.py`)
2. Verify `users.account_mode` and profile table names in Postgres
3. Deploy frontend with new paths and enum values
4. Run `uv run python scripts/rebuild_search_index.py --collection travelers` after Typesense is up

Recommended order: **backend migration first**, then frontend, to avoid mixed old/new API calls during rollout.

## Rollback strategy

1. **Application rollback** — redeploy previous backend/frontend images
2. **Database rollback** — manual reverse migration (not automated):
   - Rename tables back to `traveler_*` / `messenger_profiles`
   - `UPDATE users SET account_mode = 'traveler' WHERE account_mode = 'explorer'` (and connector → messenger)
   - Restore CHECK constraint and redeploy old SQL functions
3. **Typesense** — keep previous index snapshot until rollback window closes

Take a Postgres snapshot before applying `009` in production.

## Verification checklist

- [ ] Migration 009 applied without error
- [ ] Onboarding accepts `explorer` / `connector` only
- [ ] Explorer profile CRUD on `/v1/explorers/profile`
- [ ] Connector can search on `/v1/explorers/search` with `trip:join`
- [ ] Discovery snapshots rebuild for explorer users
- [ ] Outbox syncs to Typesense `travelers` collection
- [ ] Full pytest suite green
