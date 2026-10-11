# Matrix remediation validation

Implemented across `chatapp-backend` and `connect-carry` and validated using an
isolated Docker stack. No application database was reset, no applied checksums
were repaired, and no external credentials were rotated. No custom Java extension,
MAS, or removed monitoring service was added.

## Passing checks

- Backend pytest: **202 passed**, 4 integration/e2e tests deselected; the separate
  real-browser harness exercised PostgreSQL, Keycloak, and Synapse.
- Frontend Vitest: **115 passed** across 29 files.
- Frontend production build succeeds and emits the Rust Crypto WASM asset.
- Changed backend files pass Ruff and Black; changed frontend source, browser
  harness, and unit tests pass ESLint with two nonfatal provider warnings.
- Development Compose configuration validates.
- All 15 existing SQL migrations apply to a fresh isolated PostgreSQL database.
  Repeated execution and two concurrent runners both skip already applied files.
- Both repositories pass `git diff --check`.

## Real-browser coverage

Hosted application and Matrix SSO create nonempty real Synapse device IDs.
Two users exchange encrypted messages; intentional identical messages remain
separate events. Reload retains decryption. A second device restores backed-up
history using its existing recovery key; matching SAS values complete verification.
A competing tab cannot acquire crypto ownership. Current-device logout revokes its
tokens while preserving both another device of the same user and another user.
All-device logout revokes the recorded devices of its user.

A PostgreSQL trigger injects a local transaction failure: logout returns `503` and
the original BFF session remains usable. Pausing only the isolated Synapse service
makes logout report durable pending remote work while local access is rejected.
After unpause, the worker invalidates the targeted device; unrelated devices remain
usable. Unit regressions cover callback replay and identity mismatch, missing
devices, attachment denial, alias reconciliation, redirect validation, callback
log redaction, refresh ambiguity, storage failure, invitation authorization, and
persistent transaction IDs for retries.

The browser harness invokes production client and recovery helpers; it does not
replace a visual review of every React dialog or production ingress validation.
Production HTTPS, exact OIDC redirects, required secrets, and dedicated client
configuration still need to be set by the operator before deployment.

## Existing repository failures

Full frontend type checking reports four errors in
`src/app/search/components/UserSearchBar.tsx` and `src/app/search/pages/SearchPage.tsx`:
a union of search clients does not expose both roles' methods. No Matrix type
errors remain. Full frontend lint still reports existing errors in files outside
this change; the changed Matrix files pass. Full backend Ruff reports three
existing import-order errors in `scripts/geo_sync/{loader,orchestrator,persistence}.py`.
These unrelated files were not modified to hide the failures.

See [Matrix architecture and contracts](matrix-chat-platform.md) and
[isolated test setup](matrix-integration-testing.md) for configuration and reproduction.
