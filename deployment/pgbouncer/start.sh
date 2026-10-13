#!/bin/sh
set -eu

: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"
: "${DB_NAME:=chatapp}"
: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_PORT:=5432}"
: "${PGBOUNCER_PORT:=6432}"
: "${PGBOUNCER_POOL_MODE:=transaction}"
: "${PGBOUNCER_DEFAULT_POOL_SIZE:=10}"
: "${PGBOUNCER_RESERVE_POOL_SIZE:=5}"
: "${PGBOUNCER_MAX_CLIENT_CONN:=100}"

case "$DB_USER$DB_PASSWORD$DB_NAME$POSTGRES_HOST" in
  *'
'*) echo "PgBouncer database settings must not contain newlines" >&2; exit 1 ;;
esac
case "$DB_USER" in
  *[!A-Za-z0-9_.-]*) echo "DB_USER contains unsupported PgBouncer config characters" >&2; exit 1 ;;
esac
case "$DB_NAME" in
  *[!A-Za-z0-9_.-]*) echo "DB_NAME contains unsupported PgBouncer config characters" >&2; exit 1 ;;
esac
case "$POSTGRES_HOST" in
  *[!A-Za-z0-9_.:-]*) echo "POSTGRES_HOST contains unsupported PgBouncer config characters" >&2; exit 1 ;;
esac
case "$PGBOUNCER_POOL_MODE" in
  transaction) ;;
  *) echo "PGBOUNCER_POOL_MODE must be transaction" >&2; exit 1 ;;
esac
for numeric_setting in "$POSTGRES_PORT" "$PGBOUNCER_PORT" "$PGBOUNCER_DEFAULT_POOL_SIZE" \
  "$PGBOUNCER_RESERVE_POOL_SIZE" "$PGBOUNCER_MAX_CLIENT_CONN"; do
  case "$numeric_setting" in
    ''|*[!0-9]*) echo "PgBouncer numeric settings must contain only digits" >&2; exit 1 ;;
  esac
done

escape_quoted() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

auth_file=/tmp/pgbouncer-userlist.txt
config_file=/tmp/pgbouncer.ini
printf '"%s" "%s"\n' "$(escape_quoted "$DB_USER")" "$(escape_quoted "$DB_PASSWORD")" > "$auth_file"
chmod 600 "$auth_file"

cat > "$config_file" <<EOF
[databases]
${DB_NAME} = host=${POSTGRES_HOST} port=${POSTGRES_PORT} dbname=${DB_NAME} user=${DB_USER}

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = ${PGBOUNCER_PORT}
auth_type = scram-sha-256
auth_file = ${auth_file}
pool_mode = ${PGBOUNCER_POOL_MODE}
default_pool_size = ${PGBOUNCER_DEFAULT_POOL_SIZE}
reserve_pool_size = ${PGBOUNCER_RESERVE_POOL_SIZE}
max_client_conn = ${PGBOUNCER_MAX_CLIENT_CONN}
max_prepared_statements = 100
pidfile = /tmp/pgbouncer.pid
EOF

exec /usr/bin/pgbouncer "$config_file"
