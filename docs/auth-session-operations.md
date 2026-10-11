# Authentication and session operations

Authentication uses standard Keycloak hosted browser flows and server-side BFF
sessions. Google login remains available through Keycloak. The application does
not build or load a custom Java extension; its login theme is static content.

Password changes and recovery follow Keycloak's built-in behavior. There is no
custom credential-version claim, transactional password-change bridge, or event
receiver. The previous design's reset/login version-ordering guarantee is no
longer implemented. BFF and user-bearer requests check that the account and
associated Keycloak session remain active; provider outages fail closed with
`503 auth_provider_unavailable`.

Logout commits local session revocation and durable remote work together.
`200` confirms remote completion; `202` indicates durable pending termination;
`503 local_revocation_failed` indicates local revocation could not complete.
Opaque-cookie ownership and the session-bound CSRF secret authorize logout
without contacting Keycloak first, so a provider outage cannot prevent local
revocation.

Remote retries delete only stored Keycloak session identifiers, using the
standard Admin REST API for online and offline sessions. Current-device logout
targets its BFF session. All-device logout targets the user's local sessions at
the recorded cutoff and their associated Keycloak sessions. It does not sweep
provider sessions without a corresponding targeted BFF row or invoke user-wide
logout. New logins with different session identifiers remain unaffected.

Structured logs and request correlation IDs remain. External metrics, `/metrics`,
tracing exporters, monitoring containers, dashboards, and scrape configuration
have been removed. Use `/health/live`, `/health/ready`, application logs, and the
`auth_remote_operations` table to diagnose failures and pending logout work.

For a fresh environment, build the themed Keycloak image with
`rtk proxy docker compose build keycloak`. SQL changes target fresh setup only;
do not repair old migration histories or delete databases automatically.
