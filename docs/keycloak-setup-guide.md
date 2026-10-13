# Keycloak Setup Guide (One-Time)

Keycloak is **no longer imported from realm JSON** at Docker startup. Configure the realm manually once (or use your own IaC). Reference structure: [`deployment/keycloak/realm-chatapp.json.example`](../deployment/keycloak/realm-chatapp.json.example).

## Prerequisites

- Keycloak 26 running (see `docker compose up keycloak`); configure `POSTGRES_HOST` and provision the `keycloak` database and role first
- Admin console: `http://localhost:8180` (bootstrap via `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD`, default `admin` / `admin`)

## 1. Create realm

- Realm name: **`chatapp`**
- Email verification: enabled
- Login with email: enabled

## 2. Clients (keep existing IDs)

| Client ID | Type | Purpose |
|-----------|------|---------|
| `chatapp-web` | Public | Browser OAuth / execute-actions email |
| `chatapp-api` | Bearer-only | JWT audience + client roles |
| `chatapp-backend-admin` | Confidential + service account | Admin REST API |

### chatapp-web

- Standard flow, PKCE
- Valid redirect URIs: BFF callback + frontend verify URLs (see `AUTH_CALLBACK_URL`, `AUTH_EMAIL_VERIFY_REDIRECT_URL` in config)
- Enable **direct access grants** only if you use `POST /v1/auth/signin/password`

### chatapp-api

- Add client roles matching `auth.default_signup_roles` in `config.yaml`, e.g.:

  - `profile:update`, `session:manage`, `message:send`, `message:create-room`, `trip:create`, `trip:update`, `trip:join`

### chatapp-backend-admin

- Service account enabled
- Assign realm-management roles: `manage-users`, `view-users`, `query-users` (minimum for user lifecycle)
- Copy client secret → `KEYCLOAK_ADMIN_CLIENT_SECRET`

## 3. Environment variables

Set in `.env`:

```env
KEYCLOAK_ENABLED=true
KEYCLOAK_BASE_URL=http://localhost:8180
KEYCLOAK_ISSUER_URL=http://localhost:8180/realms/chatapp
KEYCLOAK_REALM=chatapp
KEYCLOAK_WEB_CLIENT_ID=chatapp-web
KEYCLOAK_WEB_CLIENT_SECRET=...
KEYCLOAK_ADMIN_CLIENT_ID=chatapp-backend-admin
KEYCLOAK_ADMIN_CLIENT_SECRET=...
KEYCLOAK_AUDIENCE=chatapp-api
```

## 4. Optional: Google IdP

When `KEYCLOAK_GOOGLE_CLIENT_ID` and `KEYCLOAK_GOOGLE_CLIENT_SECRET` are set, the API configures the Google identity provider on startup (after realm bootstrap and SMTP):

- Alias **`google`** by default (`KEYCLOAK_GOOGLE_IDP_ALIAS`)
- **`hideOnLoginPage`** enabled by default (`KEYCLOAK_GOOGLE_IDP_HIDE_ON_LOGIN_PAGE=true`) so users sign in via `kc_idp_hint=google`, not the Keycloak form
- Merges BFF and frontend redirect URIs from `AUTH_CALLBACK_URL`, `AUTH_DEFAULT_POST_SIGNIN_REDIRECT_URL`, and `AUTH_EMAIL_VERIFY_REDIRECT_URL` into `chatapp-web`

In Google Cloud Console, set the OAuth redirect URI to:

```text
http://localhost:8180/realms/chatapp/broker/google/endpoint
```

Manual apply (same as startup logic):

```bash
uv run python scripts/configure_keycloak_google.py
```

Add to `.env`:

```env
KEYCLOAK_GOOGLE_CLIENT_ID=your-google-client-id
KEYCLOAK_GOOGLE_CLIENT_SECRET=your-google-client-secret
```

## 5. SMTP (required for signup verification emails)

Set `KEYCLOAK_SMTP_*` in `.env`. When `KEYCLOAK_SMTP_HOST` is set, the API applies SMTP to the realm on startup (after realm bootstrap).

Manual apply or test:

```bash
uv run python scripts/configure_keycloak_smtp.py [--test]
```

Without SMTP, `POST /v1/auth/signup/start` fails at `send-verify-email` with `keycloak_integration_error` (503).

## 6. Verify backend startup

**Local auto-bootstrap:** When `KEYCLOAK_AUTO_BOOTSTRAP=true` (default in `config.yaml` for local), the API creates the `chatapp` realm from [`deployment/keycloak/realm-chatapp.json.example`](../deployment/keycloak/realm-chatapp.json.example) before startup validation if the OIDC well-known document returns 404. Requires `KEYCLOAK_BOOTSTRAP_ADMIN` credentials (docker-compose default `admin` / `admin`). Set `KEYCLOAK_AUTO_BOOTSTRAP=false` in production; realm provisioning must be manual or IaC.

With Keycloak configured, start the API. Startup order: realm bootstrap → SMTP → Google IdP (when configured) → validation. Startup validation checks:

- OIDC well-known document
- Service account token
- Clients `chatapp-web` and `chatapp-api` exist
- Configured signup roles exist on `chatapp-api`

Failures include remediation text in the startup error.
