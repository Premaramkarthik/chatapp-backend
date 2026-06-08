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
- Third-party API keys (Tinode, Meilisearch)

See [`.env.example`](../.env.example) for the full secret template.

## Production guardrails

When `APP_ENV=production`, `APP_DEBUG=true` fails at startup with a configuration error.

## Startup event

On successful load the backend emits a structured `CONFIGURATION_LOADED` domain event with `environment` and `keycloak_enabled`.
