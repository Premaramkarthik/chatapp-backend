# Keycloak Admin API Migration Checklist

Use this when moving from `--import-realm` to manual Keycloak configuration.

## Infrastructure

- [ ] Remove `--import-realm` from Keycloak Docker command (done in `docker-compose.yml`)
- [ ] Do **not** mount `realm-chatapp.json` at runtime
- [ ] Keep `deployment/keycloak/realm-chatapp.json.example` as reference only

## Keycloak console

- [ ] Realm `chatapp` exists
- [ ] Clients: `chatapp-web`, `chatapp-api`, `chatapp-backend-admin`
- [ ] Service account on `chatapp-backend-admin` with user-management roles
- [ ] Client roles on `chatapp-api` match `AUTH_DEFAULT_SIGNUP_ROLES`
- [ ] Redirect URIs for BFF + frontend verify/reset flows
- [ ] (Optional) Google IdP alias `google`
- [ ] (Optional) SMTP via `scripts/configure_keycloak_smtp.py`

## Application config

- [ ] Copy `.env.example` → `.env` with secrets
- [ ] Review [`config.yaml`](../config.yaml) for non-secret defaults
- [ ] Set `KEYCLOAK_*_SECRET` values from Keycloak admin console
- [ ] Ensure consolidated migration `003_functions_core.sql` is applied (`fn_users` mode 14) if using account deletion

## Smoke tests

- [ ] `GET /health/ready` returns OK
- [ ] Backend starts without startup validation errors
- [ ] `POST /v1/auth/signup/start` creates user (dev)
- [ ] Email verify / password reset actions work
- [ ] JWT-protected route accepts access token with `aud=chatapp-api`
- [ ] `DELETE /v1/users/me` (authenticated, `profile:update`)

## Rollback

Re-enable realm import temporarily by restoring the previous `docker-compose.yml` Keycloak service definition and restarting Keycloak (dev only).
