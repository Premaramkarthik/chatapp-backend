# Auth Threat Model

## Scope

This document covers the FastAPI BFF authentication flow backed by Keycloak,
Postgres, Redis, and secure browser cookies.

## Assets

- Keycloak access, refresh, and ID tokens
- Opaque BFF session cookie
- CSRF token
- Keycloak admin client credentials
- User identity and account mode
- Session/device metadata
- Security audit events

## Primary Risks And Controls

### XSS

Risk: attacker executes JavaScript in the browser and performs user actions.

Controls:
- Access and refresh tokens are never exposed to JavaScript.
- Session cookie is `HttpOnly`.
- CSP is enabled through middleware.
- API responses must avoid rendering untrusted HTML.

### CSRF

Risk: attacker causes a browser to send authenticated unsafe requests.

Controls:
- `SameSite=Lax` session cookie by default.
- Double-submit CSRF token for unsafe methods.
- Strict CORS allowlist from environment configuration.

### Token Theft

Risk: OAuth tokens are stolen from logs, database, Redis, browser storage, or memory dumps.

Controls:
- Browser stores only opaque session ID.
- OAuth tokens are encrypted before Postgres persistence.
- Logs must never include tokens, auth codes, cookies, or secrets.
- Redis stores hot session metadata, not raw OAuth tokens.

### Replay And Session Fixation

Risk: attacker reuses an auth code, signin state, or session ID.

Controls:
- PKCE verifier is stored encrypted.
- OAuth state is hashed and single-use.
- Callback consumes state atomically.
- Session IDs are generated after token exchange.
- Existing supplied session IDs are ignored during signin.

### Refresh Token Theft Or Reuse

Risk: refresh token is reused or refresh storms overload Keycloak.

Controls:
- Refresh tokens are encrypted at rest.
- Redis single-flight locks protect refresh per session.
- Refresh failures are audited.
- Suspicious refresh reuse marks sessions `COMPROMISED`.

### Privilege Escalation

Risk: business modes are confused with security roles.

Controls:
- Realm roles are limited to `admin`, `moderator`, `support`, and `system`.
- API authorization uses client capability roles.
- `traveler`, `messenger`, and `both` are app `account_mode` values only.
- Account mode changes never call Keycloak or alter token roles.

### Open Redirect

Risk: attacker abuses signin/logout redirects for phishing.

Controls:
- Post-signin redirect origins are allowlisted.
- Callback URL is fixed by server configuration.
- Logout redirect uses configured allowlisted URL.

### SSRF

Risk: attacker influences backend Keycloak/Admin URLs.

Controls:
- Keycloak public/internal/admin URLs come only from environment.
- User-controlled redirect URIs are never fetched by the backend.

### Redis Compromise Or Outage

Risk: hot auth cache is unavailable or tampered with.

Controls:
- Postgres remains the source of truth.
- Redis TTL never exceeds database session expiry.
- Logout writes Postgres first, then Redis revoked marker.
- Redis outage falls back to Postgres and emits metrics.

### PII Leakage

Risk: logs or audit tables expose sensitive user data.

Controls:
- Audit stores hashed email, IP, and user-agent values.
- Structured logs use request IDs and avoid raw identifiers where possible.
- Password reset responses are generic to prevent user enumeration.

### Signup Abuse

Risk: attacker creates spam accounts, abuses SMTP, or enumerates users.

Controls:
- Signup requires `Idempotency-Key`.
- Redis-backed signup limits cover IP, device fingerprint, email domain, and resend.
- Disposable email domains are blocked before Keycloak or SMTP work.
- Public signup and resend responses are generic.
- Verification sends are tracked with cooldown and max-send counters.

### Partial Signup Failure

Risk: Keycloak and local Postgres account state diverge.

Controls:
- Local pending account is created before Keycloak user creation.
- Keycloak subject is linked after successful Admin REST creation.
- Email send failures leave account recoverable through resend.
- Outbox events capture lifecycle steps for future retries/workers.
