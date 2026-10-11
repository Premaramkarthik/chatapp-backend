# Isolated Matrix browser tests

The harness uses PostgreSQL on `127.0.0.1:15439`, Keycloak on `127.0.0.1:18080`,
Synapse on `127.0.0.1:18008`, an API on `127.0.0.1:18000`, and Vite on
`127.0.0.1:18030`. Keep those ports free. Its fixed credentials are test-only.
The Compose project is `paripath-matrix-integration`; PostgreSQL and Synapse data
are disposable tmpfs data. Do not substitute an application DSN.

From the backend checkout:

```bash
rtk proxy docker build -t paripath-keycloak:local docker/keycloak
rtk proxy python3 scripts/setup_matrix_integration.py
rtk proxy docker compose -f /tmp/paripath-matrix-integration/compose.yaml up -d
rtk proxy uv run python scripts/run_migrations.py --database-url postgresql://matrix_test:matrix-test-only@127.0.0.1:15439/matrix_test
rtk proxy uv run python scripts/run_matrix_integration_api.py
```

Wait for Keycloak and Synapse before starting the API; the API setup registers a
service admin and configures test users and capabilities only in `matrix-test`.
From `connect-carry`, in another terminal:

```bash
rtk proxy npm ci
rtk proxy npx playwright install chromium
rtk proxy env MATRIX_BACKEND_DIR=/absolute/path/chatapp-backend npm run test:matrix:browser
```

The test uses hosted login, production client helpers, two users, three real devices,
encrypted delivery, reload, encrypted backup recovery, SAS comparison, cross-tab
ownership, and scoped logout. Traces, screenshots, and videos are disabled to avoid
capturing credentials. A recovery key is retained with mode `0600` under the isolated
`/tmp/paripath-matrix-integration` directory to permit reruns; never commit it.

For a fresh run, stop only this named test Compose project, remove only its test
recovery-key artifact, and recreate the test stack. Never reset application databases,
repair checksums, rotate external credentials, or reuse production accounts.
The fixture refuses database hosts, ports, and names outside its isolated DSN.

Unit tests separately inject provider failures, ambiguous refresh outcomes, malformed
credentials, identity mismatch, callback replay, attachment denial, and retry failures.
Local revocation must fail with `503` if its transaction cannot commit; committed
revocation with pending remote work returns `202`. Durable operation targets must
remain unchanged while retrying. Inspect the test database's pending operation rows
when diagnosing interrupted runs.
