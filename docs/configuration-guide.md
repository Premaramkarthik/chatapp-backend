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

## .env (secrets only)

Keep these in `.env` or your secret manager — **not** in `config.yaml`:

- `DB_PASSWORD`, `REDIS_URL`
- `KEYCLOAK_WEB_CLIENT_SECRET`, `KEYCLOAK_ADMIN_CLIENT_SECRET`
- `AUTH_TOKEN_ENCRYPTION_KEY`
- SMTP credentials for the optional ops script
- Third-party API keys (Typesense admin key)

See [`.env.example`](../.env.example) for the full secret template.

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
