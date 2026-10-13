# Matrix encrypted chat

The application authorizes business connections; Synapse stores encrypted room events.
Keycloak authenticates both the BFF and Synapse through separate OIDC clients.
The browser owns a real Synapse device and performs encryption using Rust Crypto.
Application UUIDs, Matrix localparts, and MXIDs remain stable.

## Identity and login

Configure the confidential `veliqone-matrix` Keycloak client with Authorization Code,
PKCE, and the exact redirect `https://<matrix-host>/_synapse/client/oidc/callback`.
Direct Access Grants and automatic email-based linking are disabled. Synapse account
registration through OIDC is disabled: provisioning explicitly binds the verified
Keycloak `sub` to the existing MXID using external provider `oidc-keycloak`.
Conflicting subjects fail rather than reassigning identities. Provisioning does not
create or store a user's Matrix password. The legacy password column stays empty.

`POST /v1/chat/matrix/signin/start` requires a usable BFF cookie and CSRF header.
It returns `{authorization_url}`. The browser follows Synapse SSO to Keycloak.
`GET /v1/chat/matrix/callback?state=...&loginToken=...` consumes the single-use state,
requires the initiating BFF session, exchanges the login token server-side, and
checks the exact expected MXID and requested nonempty device ID. It redirects to
`MATRIX_POST_LOGIN_URL` without tokens or profile payloads. A pre-recorded cleanup
operation handles abandoned callbacks and devices created before persistence fails.

`GET /v1/chat/matrix/session` returns `{homeserver_url, matrix_user_id, user_id,
device_id, access_token, expires_in}` only for that browser's BFF session.
The frontend normalizes the Matrix identity from `matrix_user_id`. Credentials
are encrypted in PostgreSQL `matrix_sessions`; no user-wide credential cache exists.
A missing or unusable session returns `409` with `matrix_login_required`.
`POST /v1/chat/matrix/session/refresh` exchanges supported refresh tokens under a
PostgreSQL row lock. Missing/invalid tokens and ambiguous exchange outcomes require
SSO; a proven pre-exchange connection failure is retryable. Administrative tokens
are confined to bounded internal room provisioning and never returned to browsers.

## Authorization and provisioning

Only active, unblocked application connections can provision a conversation.
`matrix_room_operations` records durable intent and retries. A PostgreSQL advisory
lock serializes each connection. The deterministic private alias is
`#conn_<connection-uuid>:<server-name>`. Reconciliation verifies exactly the two
expected joined/invited participants and `m.megolm.v1.aes-sha2` before adoption.
Room mappings track provisioning and invitation separately from business permission.
`POST /v1/chat/matrix/rooms/membership?room_id=...` reconciles actual joined members
using the caller's device session; an invitation alone does not mean chat is ready.

All attachment searches and mutations require local room authorization. Metadata
updates additionally require their original owner. Backend message search is retired
(`410 matrix_client_search_required`); browser search covers locally decrypted
loaded history. Sensitive business notifications remain in application APIs;
server-side plaintext custom Matrix events return `410 matrix_client_encryption_required`.

## Browser encryption and recovery

Use standard Matrix `/sync`. The legacy Sliding Sync proxy, database, secrets,
and ports are removed. Rust Crypto's WASM is excluded from Vite dependency
prebundling so its asset URL resolves correctly. Production builds emit the WASM
asset; serve it as `application/wasm`.

Crypto databases and encrypted outgoing queues are namespaced by homeserver,
MXID, and device ID. A browser Web Lock permits one crypto owner per namespace.
Other tabs explain ownership and offer reconnect after the owner closes. Missing
persistent storage or lock support fails visibly. Never automatically erase stores
or queues to repair initialization. Initialization is serialized and stale clients
are stopped before reuse. Sending requires initial sync, both authorized participants
joined, an encrypted room, and successful encryption preparation.

Unverified devices are allowed with warnings. Device verification uses Matrix SAS;
users compare emoji/numbers on both devices before confirmation. Cross-signing and
key backups use SDK operations, not backend advisory flags. Initial recovery setup
shows a recovery key for the user to save. Existing secret storage is preserved;
a new device enters the existing recovery key or verifies with a trusted device.
Encrypted backup restoration imports room keys to recover history.

Outgoing messages get random transaction IDs, persisted in an AES-GCM encrypted
IndexedDB queue before exchange and reused on retries. Two intentional identical
messages get different IDs. Attachment bytes are AES-CTR encrypted before upload;
the key/IV/hash descriptor travels inside the encrypted message. Protocol membership,
redactions, and Matrix reaction relations remain Matrix metadata, not business payloads.

## Revocation and failures

BFF revocation and durable Matrix device targets commit in the same PostgreSQL
transaction. Current-device logout targets only its BFF session's Matrix device;
all-device logout snapshots applicable devices and in-flight login attempts at its
cutoff. Retries retain those identifiers and never expand to user-wide Matrix logout.
Real Synapse device deletion invalidates its tokens. Account deletion first disables
local access and records remote Matrix deactivation before local cascading cleanup.

`200` means local revocation committed and remote termination completed. `202`
means local revocation completed with retryable remote work and an operation ID.
`503` means local revocation could not commit. The frontend must retain auth state
on failed local revocation. Remote outages cannot restore revoked local access.
Device removal also reports remote completion honestly; metadata flags are advisory.

The outbox worker retries authentication and room operations and expires abandoned
Matrix sessions. Inspect pending `auth_remote_operations` and `matrix_room_operations`
when reconciling outages; error fields contain exception classes, never token bodies.
Callback query parameters are redacted from access logs; diagnostic locals are disabled.

## Deployment and fresh setup

Development infrastructure binds to loopback. Synapse's `skip_verification: true`
is development-only to permit HTTP metadata endpoints; signatures and issuer checks
still apply. Production requires HTTPS, exact redirect origins, distinct application/
Synapse/Keycloak database credentials, and startup-rendered secrets. Publish client
and `/_synapse/client` SSO paths; do not publish Synapse administration externally.
Existing realms need the dedicated Keycloak client configured explicitly before SSO.

This change edits existing migrations for **fresh setups only**. Never reset an
existing database or repair migration checksums automatically. Preserve existing
MXIDs and subject bindings; unresolved ownership requires an explicit support flow.

## Validation

Run `rtk proxy uv run pytest -m "not integration and not e2e"`, then frontend
`rtk proxy npm test`, `rtk proxy npm run lint`, `rtk proxy npx tsc --noEmit`, and
`rtk proxy npm run build`. See [Matrix integration testing](matrix-integration-testing.md)
for isolated Docker-backed SSO, encrypted delivery, backup recovery, and device
revocation checks. These services use dedicated ports and disposable test data;
application databases and external credentials are never modified by the harness.
