"""Generate an isolated, disposable integration stack without touching app services."""

import json
from pathlib import Path

r = Path(__file__).resolve().parents[1]
d = Path("/tmp/paripath-matrix-integration")
d.mkdir(exist_ok=True)
realm = json.loads((r / "docker/keycloak/realm-chatapp.json.example").read_text())
realm["realm"] = "matrix-test"
realm["sslRequired"] = "none"
realm["users"] = realm.get("users", [])
for name in ["alice", "bob"]:
    realm["users"].append(
        {
            "username": name,
            "email": name + "@example.com",
            "emailVerified": True,
            "enabled": True,
            "firstName": name.title(),
            "lastName": "Test",
            "credentials": [
                {"type": "password", "value": "MatrixTestPassword42!", "temporary": False}
            ],
        }
    )
for c in realm["clients"]:
    if c["clientId"] == "chatapp-web":
        c["redirectUris"] = ["http://localhost:18000/v1/auth/signin/callback"]
        c["attributes"]["post.logout.redirect.uris"] = "http://localhost:18030/"
    if c["clientId"] == "paripath-matrix":
        c["redirectUris"] = ["http://localhost:18008/_synapse/client/oidc/callback"]
(d / "realm.json").write_text(json.dumps(realm))
(d / "synapse.yaml").write_text("""server_name: matrix.test
public_baseurl: http://localhost:18008/
pid_file: /data/synapse.pid
listeners:
- port: 8008
  tls: false
  type: http
  resources:
  - names: [client]
database:
  name: sqlite3
  args:
    database: /data/homeserver.db
signing_key_path: /data/signing.key
registration_shared_secret: matrix-integration-registration-secret
macaroon_secret_key: matrix-integration-macaroon-secret
form_secret: matrix-integration-form-secret
report_stats: false
enable_registration: false
rc_login:
  address: {per_second: 100, burst_count: 1000}
  account: {per_second: 100, burst_count: 1000}
oidc_providers:
- idp_id: keycloak
  idp_name: PariPath
  issuer: http://localhost:18080/realms/matrix-test
  discover: false
  skip_verification: true
  pkce_method: always
  client_id: paripath-matrix
  client_secret: dev-matrix-oidc-change-me
  authorization_endpoint: http://localhost:18080/realms/matrix-test/protocol/openid-connect/auth
  token_endpoint: http://keycloak:8080/realms/matrix-test/protocol/openid-connect/token
  userinfo_endpoint: http://keycloak:8080/realms/matrix-test/protocol/openid-connect/userinfo
  jwks_uri: http://keycloak:8080/realms/matrix-test/protocol/openid-connect/certs
  scopes: [openid, profile]
  enable_registration: false
  allow_existing_users: false
  user_mapping_provider:
    config:
      subject_template: "{{ user.sub }}"
      localpart_template: "{{ user.sub }}"
sso:
  client_whitelist: ["http://localhost:18000/v1/chat/matrix/callback?"]
""")
(d / "compose.yaml").write_text("""name: paripath-matrix-integration
services:
  postgres:
    image: >-
      postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24
    environment:
      POSTGRES_USER: matrix_test
      POSTGRES_PASSWORD: matrix-test-only
      POSTGRES_DB: matrix_test
    ports: ["127.0.0.1:15439:5432"]
    tmpfs: [/var/lib/postgresql/data]
  keycloak:
    image: paripath-keycloak:local
    command: [start-dev, --import-realm]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: test-admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: test-admin-password
      KC_HOSTNAME: http://localhost:18080
    ports: ["127.0.0.1:18080:8080"]
    volumes: ["./realm.json:/opt/keycloak/data/import/realm.json:ro"]
  synapse:
    image: >-
      matrixdotorg/synapse:latest@sha256:abeb932f2a9293fcbb886d5ddd0f55a34d532708ebb8dc5642934dd91ca26237
    user: "0:0"
    entrypoint: [python, -m, synapse.app.homeserver, --config-path, /config/synapse.yaml]
    tmpfs: [/data]
    ports: ["127.0.0.1:18008:8008"]
    volumes: ["./synapse.yaml:/config/synapse.yaml:ro"]
    depends_on: [keycloak]
""")
