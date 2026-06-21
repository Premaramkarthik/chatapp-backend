#!/bin/sh
# Separate DB for the MSC3575 sliding-sync proxy (not Synapse's postgres schema).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	SELECT 'CREATE DATABASE syncv3'
	WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'syncv3')\gexec
EOSQL
