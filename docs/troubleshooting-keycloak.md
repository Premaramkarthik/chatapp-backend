# Troubleshooting — Keycloak & Auth

## Password sign-in returns invalid_grant

**Cause (client config):** `directAccessGrantsEnabled` is false on `chatapp-web`.

**Fix:** Enable direct access grants on the public client in Keycloak (dev only) or use authorization code flow.

**Cause (unverified email):** Keycloak returns `invalid_grant` with `Account is not fully set up` when the user still has the `VERIFY_EMAIL` required action (common after signup before clicking the email link).

**Fix:** Click the verification link in the inbox, or call `POST /v1/auth/signup/resend` with the signup email. The BFF maps this to `email_verification_required` (not a wrong-password error).

## Signup succeeds but no email

- SMTP not configured on realm
- Gmail/app-password blocked — run `scripts/configure_keycloak_smtp.py --test`
- User already exists in Keycloak (409) — check admin console

## JWT validation fails (401)

- Wrong `KEYCLOAK_AUDIENCE` (must match token `aud`, typically `chatapp-api`)
- Wrong issuer (`KEYCLOAK_ISSUER_URL`)
- Expired token — check `JWT_CLOCK_LEEWAY_SEC`
- Redis JWKS stale — delete `auth:jwks:chatapp` keys

## Signup roles not applied

- Roles must exist on **`chatapp-api`** client, not realm roles
- Startup validation lists missing roles at boot

## Google social login broken

- IdP alias must match `KEYCLOAK_GOOGLE_IDP_ALIAS` (default `google`)
- Redirect URIs on `chatapp-web` must include frontend callback

## Fresh Docker stack empty

Expected after removing realm import. Follow [keycloak-setup-guide.md](./keycloak-setup-guide.md).

## Admin console shows "Local access required"

**Cause:** Keycloak 26 needs a bootstrapped admin user. Legacy `KEYCLOAK_ADMIN` env vars are ignored.

**Fix:** `docker-compose.yml` sets `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD`. Confirm the bootstrap credentials and that Keycloak can connect to its pre-provisioned database on the external PostgreSQL server. This Compose stack does not include a PostgreSQL container; use your database provider's administrative tools to inspect or repair Keycloak database state.

```bash
docker compose stop keycloak
docker compose up -d keycloak
```

Open **http://localhost:8180** (use `localhost`, not `127.0.0.1`) and sign in with the bootstrap credentials.
