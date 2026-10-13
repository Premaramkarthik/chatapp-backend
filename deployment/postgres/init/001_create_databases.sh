#!/bin/sh
set -eu
: "${APP_DB_PASSWORD:?Required}" "${KEYCLOAK_DB_PASSWORD:?Required}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v app_pass="$APP_DB_PASSWORD" -v kc_pass="$KEYCLOAK_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE chatapp LOGIN PASSWORD %L', :'app_pass') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname='chatapp')\gexec
SELECT format('CREATE ROLE keycloak LOGIN PASSWORD %L', :'kc_pass') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname='keycloak')\gexec
SELECT 'CREATE DATABASE chatapp OWNER chatapp' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='chatapp')\gexec
SELECT 'CREATE DATABASE keycloak OWNER keycloak' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='keycloak')\gexec
SQL
