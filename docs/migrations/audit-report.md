# Migration Audit Report

**Date:** 2026-06-06  
**Scope:** `/migrations` (pre-refactor: 15 files, post-refactor: 7 files)  
**Method:** Full file read, application code cross-reference (`infrastructure/database/repositories/*`, `domains/*`), fresh-install validation on `chatapp_migration_test`.

## Executive Summary

The legacy migration chain applied the same database objects multiple times across sequential files. The worst offenders were **`fn_users`** (redefined 6 times) and **`fn_tinode_conversation_mappings`** (redefined 2 times). Table evolution for `users` was spread across four files via `ALTER TABLE`, constraint drop/recreate, and index replacement.

Consolidation reduced **15 migration files → 7**, with **one authoritative definition** per function, trigger batch, and table shape. Final application-visible behavior is preserved (modes 1–14 for `fn_users`, modes 1–5 for `fn_tinode_conversation_mappings`).

## Inventory (Pre-Refactor)

| File | Primary objects | Override / debt |
|------|-----------------|-----------------|
| `001_create_core_tables.sql` | `users`, `tinode_user_mappings`, indexes | `users.status` constraint superseded in 004 |
| `002_create_core_functions.sql` | `set_updated_at`, triggers, `fn_health`, `fn_users` v1, `fn_tinode_user_mappings` | `fn_users` superseded 5× |
| `003_create_auth_tables.sql` | auth tables, `account_mode`, `fn_users` v2 | replaces `fn_users`, drops/recreates `users_account_mode_check` |
| `004_create_signup_lifecycle.sql` | signup columns, `fn_signup_sessions`, `fn_users` v3 | alters `users`, drops `idx_users_email`, replaces `users_status_check`, `fn_users` v3 |
| `005_geo_reference.sql` | geo tables, seeds, `pg_trgm` | extension split from pgcrypto |
| `006_explorer_connector_profiles.sql` | profile tables, triggers | — |
| `007_travel_plans.sql` | travel tables, triggers | — |
| `008_discovery_connections.sql` | social tables, triggers | — |
| `009_tinode_conversations.sql` | `tinode_conversation_mappings` | — |
| `010_search_outbox.sql` | `search_outbox_events` | — |
| `011_create_social_functions.sql` | social helpers + 10 `fn_*`, **`fn_tinode_conversation_mappings` v1** | chat fn superseded in 012 |
| `012_tinode_chat_functions.sql` | **`fn_tinode_conversation_mappings` v2** (authoritative) | full function replace |
| `013_onboarding_flow.sql` | **`fn_users` v4** (mode 13) | function-only migration |
| `014_activate_pending_by_email.sql` | **`fn_users` v5** (modes 8, 10) | function-only migration |
| `015_delete_user.sql` | **`fn_users` v6** (mode 14) | function-only migration; never applied to dev DB |

## Duplicate Functions

| Function | Definitions (files) | Authoritative (kept in) | Removed versions |
|----------|---------------------|-------------------------|------------------|
| `fn_users` | 002, 003, 004, 013, 014, 015 | `003_functions_core.sql` (from 015) | 5 obsolete bodies |
| `fn_tinode_conversation_mappings` | 011 (modes 1–2), 012 (modes 1–5) | `005_functions_chat.sql` (from 012) | 011 stub (modes 1–2, status=`active` on provision) |
| `set_updated_at` | 002 only | `003_functions_core.sql` | — |
| `fn_health` | 002 only | `003_functions_core.sql` | — |
| `fn_tinode_user_mappings` | 002 only | `003_functions_core.sql` | — |
| `fn_signup_sessions` | 004 only | `003_functions_core.sql` | — |
| Social `fn_*` + helpers | 011 only | `004_functions_social.sql` | duplicate `fn_tinode_conversation_mappings` block removed |

**Net:** 2 functions had multiple versions; 1 function (`fn_users`) accounted for **6** redundant full replacements.

## Duplicate Triggers

All `updated_at` triggers used idempotent `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER` in multiple files:

| Trigger | Created in (legacy) | Consolidated in |
|---------|---------------------|-----------------|
| `trg_users_set_updated_at` | 002 | `006_triggers.sql` |
| `trg_tinode_user_mappings_set_updated_at` | 002 | `006_triggers.sql` |
| `trg_auth_sessions_set_updated_at` | 003 | `006_triggers.sql` |
| `trg_auth_device_fingerprints_set_updated_at` | 003 | `006_triggers.sql` |
| `trg_explorer_profiles_set_updated_at` | 006 | `006_triggers.sql` |
| `trg_connector_profiles_set_updated_at` | 006 | `006_triggers.sql` |
| `trg_user_privacy_settings_set_updated_at` | 006 | `006_triggers.sql` |
| `trg_travel_plans_set_updated_at` | 007 | `006_triggers.sql` |
| `trg_connection_requests_set_updated_at` | 008 | `006_triggers.sql` |
| `trg_tinode_conversation_mappings_set_updated_at` | 009 | `006_triggers.sql` |

**Net:** 10 triggers, each defined once in consolidated chain (previously scattered across 6 files).

## Duplicate Views

**None.** No `CREATE VIEW` statements exist in the migration history.

## Obsolete Migrations (Removed)

These files were **function-only overrides** or **fully merged** into consolidated files:

1. `013_onboarding_flow.sql` — merged into `fn_users` authoritative body  
2. `014_activate_pending_by_email.sql` — merged into `fn_users` authoritative body  
3. `015_delete_user.sql` — merged into `fn_users` authoritative body  
4. `003_create_auth_tables.sql` — `fn_users` v2 + table alters merged into `002_tables.sql` / `003_functions_core.sql`  
5. `011_create_social_functions.sql` — superseded by `004_functions_social.sql` (minus duplicate chat fn)  
6. `012_tinode_chat_functions.sql` — superseded by `005_functions_chat.sql`  

All 15 legacy files were removed; see [consolidation-plan.md](./consolidation-plan.md).

## Repeated Table / Constraint Changes

| Object | Legacy churn | Consolidated approach |
|--------|--------------|----------------------|
| `users.keycloak_sub` | `NOT NULL` (001) → nullable (004) | nullable in `002_tables.sql` |
| `users.status` CHECK | `active/suspended/deleted` (001) → 6 values (004) | final CHECK in `002_tables.sql` |
| `users.email` index | `idx_users_email` (001) dropped (004), partial unique added | `idx_users_email_unique` + `users_email_key` UNIQUE |
| `users` signup columns | added across 003, 004 | all columns in initial `CREATE TABLE` |
| `oauth_signin_states` | flow columns added in 004 | full column set in `002_tables.sql` |
| `tinode_conversation_mappings.status` | default `active` (009); provision uses `provisioning` (012) | CHECK includes both; fn uses `provisioning` |

## Unused Database Objects

| Object | Used by application? | Notes |
|--------|----------------------|-------|
| `explorer_profiles.onboarding_step` | No direct Python reference | Kept — column exists in domain schema path |
| `auth_outbox_events` | Yes (`auth.py` repository) | Active |
| `idx_users_email` (legacy) | **Removed** | Replaced by `idx_users_email_unique` |
| `fn_users` mode 4 | No repository call | Kept — general update API, harmless |
| Views | N/A | None defined |

No tables were removed; all 23 application tables remain.

## Application Function Mode Matrix (Verified)

| Function | Modes used in code | Final migration |
|----------|-------------------|-----------------|
| `fn_users` | 1,3,5,6,7,8,9,10,11,12,13,14 | `003_functions_core.sql` |
| `fn_signup_sessions` | 1,2,3 | `003_functions_core.sql` |
| `fn_tinode_user_mappings` | 2,3 | `003_functions_core.sql` |
| `fn_health` | 1 | `003_functions_core.sql` |
| `fn_explorer_profiles` | 1,2 | `004_functions_social.sql` |
| `fn_connector_profiles` | 2 | `004_functions_social.sql` |
| `fn_user_privacy_settings` | 2 | `004_functions_social.sql` |
| `fn_travel_plans` | 1,2 | `004_functions_social.sql` |
| `fn_explorer_current_locations` | 2 | `004_functions_social.sql` |
| `fn_discovery_snapshots` | 1,2,3,4 | `004_functions_social.sql` |
| `fn_connection_requests` | 1–5 | `004_functions_social.sql` |
| `fn_user_connections` | 1,2 | `004_functions_social.sql` |
| `fn_user_blocks` | 1,2 | `004_functions_social.sql` |
| `fn_search_outbox_events` | 1,2,3 | `004_functions_social.sql` |
| `fn_tinode_conversation_mappings` | 1,2,3,4,5 | `005_functions_chat.sql` |

## Counts

| Metric | Before | After |
|--------|--------|-------|
| Migration files | 15 | 7 |
| `fn_users` full replacements | 6 | 1 |
| `fn_tinode_conversation_mappings` replacements | 2 | 1 |
| Trigger definition sites | 6 files | 1 file |
| Obsolete function-only migrations | 3 (013–015) | 0 |
