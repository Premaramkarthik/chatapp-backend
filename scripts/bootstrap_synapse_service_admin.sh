#!/usr/bin/env sh
set -eu

SYNAPSE_URL="${SYNAPSE_URL:-http://synapse:8008}"
USER="${MATRIX_SERVICE_ADMIN_USER:-connectcarry-admin}"
PASS="${MATRIX_SERVICE_ADMIN_PASSWORD:?MATRIX_SERVICE_ADMIN_PASSWORD is required}"
SERVER_NAME="${MATRIX_SERVER_NAME:-matrix.local}"

echo "Waiting for Synapse at ${SYNAPSE_URL}..."
until curl -sf "${SYNAPSE_URL}/health" >/dev/null; do
  sleep 2
done

promote_service_admin() {
  python3 - <<'PY'
import os
import sys

import psycopg2

user = os.environ["MATRIX_SERVICE_ADMIN_USER"]
server = os.environ.get("MATRIX_SERVER_NAME", "matrix.local")
mxid = f"@{user}:{server}"
conn = psycopg2.connect(
    host=os.environ.get("PGHOST", "synapse-db"),
    user=os.environ.get("PGUSER", "synapse"),
    password=os.environ.get("PGPASSWORD", "synapse"),
    dbname=os.environ.get("PGDATABASE", "synapse"),
)
conn.autocommit = True
cur = conn.cursor()
cur.execute("UPDATE users SET admin = 1 WHERE name = %s", (mxid,))
if cur.rowcount:
    print(f"Promoted {mxid} to server admin.")
else:
    print(f"No Synapse user row for {mxid}", file=sys.stderr)
    sys.exit(1)
PY
}

echo "Ensuring Matrix service admin @${USER}:${SERVER_NAME} exists..."
set +e
output="$(register_new_matrix_user \
  -c /data/homeserver.yaml \
  -u "${USER}" \
  -p "${PASS}" \
  --admin \
  "${SYNAPSE_URL}" 2>&1)"
status=$?
set -e

if [ "${status}" -eq 0 ]; then
  echo "Service admin registered."
elif printf '%s' "${output}" | grep -qi 'already exists\|User ID already taken'; then
  echo "Service admin already exists; ensuring server-admin flag..."
  MATRIX_SERVICE_ADMIN_USER="${USER}" MATRIX_SERVER_NAME="${SERVER_NAME}" promote_service_admin
else
  printf '%s\n' "${output}" >&2
  exit "${status}"
fi
