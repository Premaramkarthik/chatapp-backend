# Operational Runbook — Auth & Keycloak

## Startup validation failure

**Symptom:** API exits on boot with `ConfigurationError` mentioning Keycloak.

| Message | Action |
|---------|--------|
| OIDC well-known unreachable | Check `KEYCLOAK_BASE_URL`, network, Keycloak pod/container |
| Admin token failed | Verify `KEYCLOAK_ADMIN_CLIENT_ID/SECRET`, service account enabled |
| Missing client | Create `chatapp-web` or `chatapp-api` in realm |
| Missing role | Add role to `chatapp-api` client; match `AUTH_DEFAULT_SIGNUP_ROLES` |

Set `APP_SKIP_STARTUP_INTEGRATIONS=true` only for local debugging — not production.

## JWKS rotation

- Background worker refreshes JWKS into Redis (`auth:jwks:{realm}`)
- Verifier order: Redis → stale Redis → live JWKS URL
- Tune TTLs in `config.yaml`: `jwt.jwks_cache_ttl`, `jwt.stale_jwks_ttl_sec`

If tokens fail after Keycloak key rotation, flush Redis JWKS keys or wait for refresh interval.

## Admin API 403

- Service account missing `manage-users` / `view-users`
- Wrong realm in `KEYCLOAK_REALM`
- Clock skew (rare); check container time sync

## Email actions failing

- Confirm `chatapp-web` redirect URIs include verify/reset URLs
- Run SMTP script or configure realm SMTP manually
- Check Keycloak server logs for `execute-actions-email` errors

## Account deletion

`DELETE /v1/users/me` requires capability `profile:update`.

Order: Keycloak user delete → local DB delete by `keycloak_sub`. Audit event: `ACCOUNT_DELETED`.

## Observability

- Domain events: `KEYCLOAK_USER_*`, `JWT_VALIDATION_FAILED`, `AUTH_SIGNUP_*`
- Admin HTTP operations emit structured logs with request correlation IDs.
- Correlation: `X-Request-ID`, `X-Correlation-ID`
