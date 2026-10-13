# Configuration Guide

The backend loads settings in this order (later wins):

1. **`config.yaml`** — non-sensitive defaults (committed)
2. **`.env`** — local secrets and overrides
3. **Process environment variables** — deployment overrides

## config.yaml

Operational defaults live in [`config.yaml`](../config.yaml) at the repository root. Nested keys map to environment variables via [`core/config/loader.py`](../core/config/loader.py).

Examples:

| YAML path | Environment variable |
|-----------|---------------------|
| `app.environment` | `APP_ENV` |
| `keycloak.realm` | `KEYCLOAK_REALM` |
| `jwt.jwks_cache_ttl` | `KEYCLOAK_JWKS_CACHE_TTL_SEC` |
| `http.timeout_seconds` | `HTTP_TIMEOUT_SECONDS` |
| `auth.default_signup_roles` | `AUTH_DEFAULT_SIGNUP_ROLES` |

Lists in YAML become comma-separated env values.

## .env (secrets and deployment details)

Keep these in `.env` or your secret manager — **not** in `config.yaml`:

- `DB_PASSWORD`, `REDIS_PASSWORD`
- `KEYCLOAK_WEB_CLIENT_SECRET`, `KEYCLOAK_ADMIN_CLIENT_SECRET`
- `AUTH_TOKEN_ENCRYPTION_KEY`
- SMTP credentials for the optional ops script
- Third-party API keys (Typesense admin key)

See [`.env.example`](../.env.example) for secrets, connection details, SMTP settings, and Docker overrides. Docker Compose reads `.env` directly and does not load `config.yaml`. Middleware policies, auth session and signup limits, database pool tuning, Matrix upload limits, Typesense collection names, and search cache durations live in YAML. Any mapped setting can still be overridden in `.env` or the process environment.

Redis builds its connection URL from `REDIS_HOST`, `REDIS_PORT`, and `REDIS_PASSWORD`. Use `localhost` when the backend runs on the host and `redis` when it runs in Docker Compose. `REDIS_URL` remains an explicit override for tests and deployments.

Application PostgreSQL pools use `DB_TARGET=pgbouncer` by default in the local `.env.example`; use `DB_TARGET=direct` to connect straight to PostgreSQL. Host-run development uses `PGBOUNCER_HOST=localhost`, while Compose containers use `PGBOUNCER_HOST=pgbouncer`. If PgBouncer cannot accept a connection after retries, the application pool falls back to the direct PostgreSQL endpoint. Migrations and geo-sync continue to use the direct endpoint because they rely on session-level database behavior.

Production Compose expects an externally managed PostgreSQL server configured with `POSTGRES_HOST` and optional `POSTGRES_PORT` (default `5432`). Provision the `chatapp` and `keycloak` databases and their login roles before deployment, using `APP_DB_PASSWORD` and `KEYCLOAK_DB_PASSWORD`; both PgBouncer and direct migration/fallback connections use the same external host.

## Search (Typesense)

When `TYPESENSE_ENABLED=true`, explorer and global search use Typesense collections synced from Postgres via the search outbox and Dramatiq workers.

| Variable | Purpose |
|----------|---------|
| `TYPESENSE_HOST`, `TYPESENSE_PORT`, `TYPESENSE_PROTOCOL` | Typesense server |
| `TYPESENSE_API_KEY` | Admin key (backend + workers only) |
| `TYPESENSE_*_COLLECTION` | Collection names (`users`, `travelers`, geo, etc.) |
| `SEARCH_CACHE_TTL_*_SEC` | Redis cache TTLs per search type |

Rebuild indexes after geo sync or bulk data changes:

```bash
uv run python scripts/rebuild_search_index.py --collection all
```

Readiness: `GET /health/ready` checks Typesense when enabled.

Full platform documentation: [typesense-search-platform.md](./typesense-search-platform.md)

## Production guardrails

When `APP_ENV=production`, `APP_DEBUG=true` fails at startup with a configuration error.

## Startup event

On successful load the backend emits a structured `CONFIGURATION_LOADED` domain event with `environment` and `keycloak_enabled`.
