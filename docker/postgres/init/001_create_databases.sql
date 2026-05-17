SELECT 'CREATE ROLE chatapp LOGIN PASSWORD ''chatapp'''
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'chatapp')\gexec

SELECT 'CREATE DATABASE chatapp OWNER chatapp'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'chatapp')\gexec

SELECT 'CREATE DATABASE keycloak OWNER chatapp'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'keycloak')\gexec

SELECT 'CREATE DATABASE tinode OWNER chatapp'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'tinode')\gexec
