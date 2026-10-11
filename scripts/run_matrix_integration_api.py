"""Run the API with explicit isolated Matrix test service settings."""

import hashlib
import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(
    {
        "APP_ENV": "test",
        "HTTP_TIMEOUT_SECONDS": "2",
        "APP_SKIP_STARTUP_INTEGRATIONS": "false",
        "APP_DEBUG": "false",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "15439",
        "DB_USER": "matrix_test",
        "DB_PASSWORD": "matrix-test-only",
        "DB_NAME": "matrix_test",
        "KEYCLOAK_ENABLED": "true",
        "KEYCLOAK_REALM": "matrix-test",
        "KEYCLOAK_BASE_URL": "http://localhost:18080",
        "KEYCLOAK_INTERNAL_BASE_URL": "http://localhost:18080",
        "KEYCLOAK_PUBLIC_BASE_URL": "http://localhost:18080",
        "KEYCLOAK_ISSUER_URL": "http://localhost:18080/realms/matrix-test",
        "KEYCLOAK_AUTO_BOOTSTRAP": "false",
        "KEYCLOAK_WEB_CLIENT_SECRET": "matrix-test-web-secret",
        "KEYCLOAK_ADMIN_CLIENT_SECRET": "matrix-test-admin-secret",
        "KEYCLOAK_BOOTSTRAP_ADMIN": "test-admin",
        "KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD": "test-admin-password",
        "KEYCLOAK_GOOGLE_CLIENT_ID": "",
        "KEYCLOAK_GOOGLE_CLIENT_SECRET": "",
        "KEYCLOAK_SMTP_HOST": "",
        "AUTH_TOKEN_ENCRYPTION_KEY": "matrix-integration-only-encryption-key",
        "AUTH_COOKIE_SECURE": "false",
        "AUTH_CALLBACK_URL": "http://localhost:18000/v1/auth/signin/callback",
        "AUTH_DEFAULT_POST_SIGNIN_REDIRECT_URL": "http://localhost:18030/auth/callback",
        "AUTH_POST_LOGOUT_REDIRECT_URL": "http://localhost:18030/",
        "AUTH_ALLOWED_REDIRECT_ORIGINS": "http://localhost:18030",
        "MIDDLEWARE_CORS_ORIGINS": "http://localhost:18030",
        "TYPESENSE_ENABLED": "false",
        "REDIS_URL": "redis://localhost:16389/0",
        "MATRIX_ENABLED": "true",
        "MATRIX_HOMESERVER_URL": "http://localhost:18008",
        "MATRIX_PUBLIC_HOMESERVER_URL": "http://localhost:18008",
        "MATRIX_SERVER_NAME": "matrix.test",
        "MATRIX_SERVICE_ADMIN_USER": "matrix-test-admin",
        "MATRIX_SERVICE_ADMIN_PASSWORD": "matrix-test-service-admin-password",
        "MATRIX_CALLBACK_URL": "http://localhost:18000/v1/chat/matrix/callback",
        "MATRIX_POST_LOGIN_URL": "http://localhost:18030/chat",
        "LOGGING_FILE": "/tmp/paripath-matrix-integration/api.log",
    }
)
import httpx

with httpx.Client(timeout=30) as http:
    admin = http.post(
        "http://localhost:18080/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "test-admin",
            "password": "test-admin-password",
        },
    ).json()["access_token"]
    headers = {"Authorization": "Bearer " + admin}
    for client_id, secret in [
        ("chatapp-web", "matrix-test-web-secret"),
        ("chatapp-backend-admin", "matrix-test-admin-secret"),
    ]:
        row = http.get(
            "http://localhost:18080/admin/realms/matrix-test/clients",
            params={"clientId": client_id},
            headers=headers,
        ).json()[0]
        row["secret"] = secret
        http.put(
            "http://localhost:18080/admin/realms/matrix-test/clients/" + row["id"],
            headers=headers,
            json=row,
        ).raise_for_status()
    admin_client = http.get(
        "http://localhost:18080/admin/realms/matrix-test/clients",
        params={"clientId": "chatapp-backend-admin"},
        headers=headers,
    ).json()[0]
    service = http.get(
        "http://localhost:18080/admin/realms/matrix-test/clients/"
        + admin_client["id"]
        + "/service-account-user",
        headers=headers,
    ).json()
    realm_client = http.get(
        "http://localhost:18080/admin/realms/matrix-test/clients",
        params={"clientId": "realm-management"},
        headers=headers,
    ).json()[0]
    roles = http.get(
        "http://localhost:18080/admin/realms/matrix-test/clients/" + realm_client["id"] + "/roles",
        headers=headers,
    ).json()
    http.post(
        "http://localhost:18080/admin/realms/matrix-test/users/"
        + service["id"]
        + "/role-mappings/clients/"
        + realm_client["id"],
        headers=headers,
        json=[
            role
            for role in roles
            if role["name"]
            in {
                "view-users",
                "manage-users",
                "query-users",
                "view-clients",
                "query-clients",
                "manage-clients",
                "view-realm",
            }
        ],
    ).raise_for_status()
    for name in ["alice", "bob"]:
        user_row = http.get(
            "http://localhost:18080/admin/realms/matrix-test/users",
            params={"username": name},
            headers=headers,
        ).json()[0]
        user_row["email"] = name + "@example.com"
        api_client = http.get(
            "http://localhost:18080/admin/realms/matrix-test/clients",
            params={"clientId": "chatapp-api"},
            headers=headers,
        ).json()[0]
        api_roles = http.get(
            "http://localhost:18080/admin/realms/matrix-test/clients/"
            + api_client["id"]
            + "/roles",
            headers=headers,
        ).json()
        http.post(
            "http://localhost:18080/admin/realms/matrix-test/users/"
            + user_row["id"]
            + "/role-mappings/clients/"
            + api_client["id"],
            headers=headers,
            json=api_roles,
        ).raise_for_status()
        http.put(
            "http://localhost:18080/admin/realms/matrix-test/users/" + user_row["id"],
            headers=headers,
            json=user_row,
        ).raise_for_status()
    nonce = http.get("http://localhost:18008/_synapse/admin/v1/register").json()["nonce"]
    user, password = "matrix-test-admin", "matrix-test-service-admin-password"
    mac = hmac.new(b"matrix-integration-registration-secret", digestmod=hashlib.sha1)
    mac.update(nonce.encode() + b"\0" + user.encode() + b"\0" + password.encode() + b"\0admin")
    response = http.post(
        "http://localhost:18008/_synapse/admin/v1/register",
        json={
            "nonce": nonce,
            "username": user,
            "password": password,
            "admin": True,
            "mac": mac.hexdigest(),
        },
    )
    if response.status_code not in (200, 400):
        response.raise_for_status()
import uvicorn

uvicorn.run("main:app", host="127.0.0.1", port=18000, access_log=False)
