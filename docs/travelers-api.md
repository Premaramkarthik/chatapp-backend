# Travelers API — End-to-End Guide

This document describes the **Travelers** HTTP API exposed at `/v1/travelers/`*. It covers authentication, authorization, request/response shapes, database side effects, search behavior, and how the ConnectCarry frontend uses these endpoints.

**Source:** `[v1/routers/travelers.py](../v1/routers/travelers.py)`

---

## Overview

The travelers API lets users:

1. **Maintain a traveler profile** (headline, bio, languages, visibility, etc.)
2. **Create travel plans** with one or more destination countries/cities
3. **Update current location** (country, city, coordinates)
4. **Search discoverable travelers** heading to a destination country (for messengers)

Profile, trip, and location writes rebuild a **discovery snapshot** in Postgres (`traveler_discovery_snapshots`). When Meilisearch is enabled, a background outbox syncs snapshots into the `travelers` search index for fast filtered search.

```mermaid
flowchart LR
  Client[Web / Mobile client]
  BFF[FastAPI /v1/travelers]
  PG[(PostgreSQL)]
  Meili[(Meilisearch)]

  Client -->|session cookie or Bearer| BFF
  BFF --> PG
  BFF -->|search when MEILI_ENABLED| Meili
  PG -->|discovery snapshot| Meili
```



---

## Prerequisites

### Authentication

All endpoints require an authenticated principal. The BFF accepts either:

- **Session cookie** (`pp_session`) from the web app — set after sign-in; includes CSRF double-submit for `POST`/`PUT`/`PATCH`/`DELETE`
- **Bearer JWT** — Keycloak access token in `Authorization: Bearer <token>`

The auth middleware attaches `KeycloakPrincipal` to `request.state` before the router runs.

### Local user record

Every handler resolves the Keycloak subject (`principal.sub`) to a row in `users` via `PostgresUserRepository.get_by_keycloak_sub`. If no local user exists, the API returns **404 User not found**.

### Account mode

Profile read/write enforces traveler account mode:


| `users.account_mode` | `GET/PUT /profile`                                          |
| -------------------- | ----------------------------------------------------------- |
| `traveler`           | Allowed                                                     |
| `messenger`          | **403** — `Traveler profile requires account_mode traveler` |


Set account mode via `PATCH /v1/users/account-mode` after onboarding.

### Capabilities (Keycloak client roles)


| Endpoint        | Required capability | Notes                                 |
| --------------- | ------------------- | ------------------------------------- |
| `GET /profile`  | Authenticated only  | No capability gate                    |
| `PUT /profile`  | `trip:create`       | Also requires `account_mode=traveler` |
| `POST /trips`   | `trip:create`       |                                       |
| `PUT /location` | `trip:create`       |                                       |
| `GET /search`   | `trip:join`         | Typical for messenger role            |


Users with the `admin` role bypass capability checks.

Default signup roles are configured in `config.yaml` / `AUTH_DEFAULT_SIGNUP_ROLES`. Ensure Keycloak assigns `trip:create` to travelers and `trip:join` to messengers (see [keycloak-setup-guide.md](./keycloak-setup-guide.md)).

---

## Endpoint reference

Base path: `**/v1/travelers`**

### GET `/profile`

Return the authenticated user's traveler profile.

**Auth:** Session or Bearer  
**Capability:** None  
**Account mode:** `traveler`

**Success — 200**

```json
{
  "user_id": "5e5f5aec-dd15-42c1-b9d2-8588a387883d",
  "headline": "Flying Tokyo → NYC in March",
  "bio": "Happy to carry small items.",
  "avatar_url": null,
  "home_country_iso": "US",
  "home_city_id": null,
  "languages": ["en", "ja"],
  "interests": ["electronics", "books"],
  "connection_availability": "open",
  "visibility": "discoverable",
  "last_active_at": "2026-06-10T04:00:00Z"
}
```

**Errors**


| Status | When                                       |
| ------ | ------------------------------------------ |
| 401    | Not authenticated                          |
| 403    | Account mode is `messenger` only           |
| 404    | Local user or traveler profile row missing |


---

### PUT `/profile`

Create or update the traveler profile. Only fields present in the body are applied (partial update via `exclude_unset`).

**Auth:** Session or Bearer  
**Capability:** `trip:create`  
**Account mode:** `traveler`

**Request body** (`[TravelerProfileUpdateRequest](../v1/schemas/travelers.py)`)


| Field                     | Type     | Constraints                                  |
| ------------------------- | -------- | -------------------------------------------- |
| `headline`                | string   | optional                                     |
| `bio`                     | string   | optional                                     |
| `avatar_url`              | string   | optional                                     |
| `home_country_iso`        | string   | 2-letter ISO                                 |
| `home_city_id`            | UUID     | optional                                     |
| `languages`               | string[] | optional                                     |
| `interests`               | string[] | optional                                     |
| `connection_availability` | enum     | `open`, `limited`, `unavailable`             |
| `visibility`              | enum     | `discoverable`, `connections_only`, `hidden` |


**Example**

```bash
curl -X PUT "http://localhost:8000/v1/travelers/profile" \
  -H "Content-Type: application/json" \
  -H "Cookie: pp_session=..." \
  -H "X-CSRF-Token: ..." \
  -d '{
    "headline": "NRT → JFK, flexible dates",
    "languages": ["en"],
    "interests": ["snacks"],
    "visibility": "discoverable",
    "connection_availability": "open"
  }'
```

**Success — 200** — Same shape as `GET /profile`.

**Side effects**

- Upserts `traveler_profiles` via `fn_traveler_profiles` mode 2
- Ensures `user_privacy_settings` row exists
- Calls `social_rebuild_discovery_snapshot(user_id)` so search index data stays current

**Logs**

- `Traveler profile upsert request received`
- `Traveler profile upsert committed`

---

### POST `/trips`

Create a travel plan with one or more ordered destinations.

**Auth:** Session or Bearer  
**Capability:** `trip:create`

**Request body** (`[TravelPlanCreateRequest](../v1/schemas/travelers.py)`)


| Field          | Type                | Required       |
| -------------- | ------------------- | -------------- |
| `title`        | string              | optional       |
| `start_date`   | date (`YYYY-MM-DD`) | optional       |
| `end_date`     | date                | optional       |
| `is_primary`   | boolean             | default `true` |
| `destinations` | array               | **min 1 item** |


Each destination:


| Field            | Type                    |
| ---------------- | ----------------------- |
| `country_iso`    | 2-letter ISO (required) |
| `city_id`        | UUID (optional)         |
| `arrival_date`   | date (optional)         |
| `departure_date` | date (optional)         |


**Example**

```bash
curl -X POST "http://localhost:8000/v1/travelers/trips" \
  -H "Content-Type: application/json" \
  -H "Cookie: pp_session=..." \
  -H "X-CSRF-Token: ..." \
  -d '{
    "title": "Spring Japan trip",
    "start_date": "2026-03-01",
    "end_date": "2026-03-20",
    "is_primary": true,
    "destinations": [
      {
        "country_iso": "JP",
        "city_id": "550e8400-e29b-41d4-a716-446655440000",
        "arrival_date": "2026-03-05",
        "departure_date": "2026-03-15"
      }
    ]
  }'
```

**Success — 201**

```json
{
  "plan": {
    "id": "...",
    "user_id": "...",
    "title": "Spring Japan trip",
    "start_date": "2026-03-01",
    "end_date": "2026-03-20",
    "is_primary": true,
    "status": "active",
    "created_at": "...",
    "updated_at": "..."
  }
}
```

**Side effects**

- Inserts `travel_plans` and `travel_plan_destinations` via `fn_travel_plans` mode 2
- Rebuilds discovery snapshot for the user

**Logs**

- `Travel plan create request received`
- `Travel plan created`

---

### PUT `/location`

Update the traveler's current location (manual source by default).

**Auth:** Session or Bearer  
**Capability:** `trip:create`

**Request body** (`[CurrentLocationUpdateRequest](../v1/schemas/travelers.py)`)


| Field         | Type                    |
| ------------- | ----------------------- |
| `country_iso` | 2-letter ISO (optional) |
| `city_id`     | UUID (optional)         |
| `latitude`    | float (optional)        |
| `longitude`   | float (optional)        |


**Example**

```bash
curl -X PUT "http://localhost:8000/v1/travelers/location" \
  -H "Content-Type: application/json" \
  -H "Cookie: pp_session=..." \
  -H "X-CSRF-Token: ..." \
  -d '{
    "country_iso": "JP",
    "latitude": 35.6762,
    "longitude": 139.6503
  }'
```

**Success — 200**

```json
{
  "location": {
    "user_id": "...",
    "country_iso": "JP",
    "city_id": null,
    "latitude": "35.6762",
    "longitude": "139.6503",
    "source": "manual",
    "updated_at": "..."
  }
}
```

**Side effects**

- Upserts `traveler_current_locations` via `fn_traveler_current_locations` mode 2
- Rebuilds discovery snapshot

---

### GET `/search`

Search **discoverable** travelers by destination country. Intended for messengers browsing routes.

**Auth:** Session or Bearer  
**Capability:** `trip:join`

**Query parameters**


| Param                 | Required | Description                                               |
| --------------------- | -------- | --------------------------------------------------------- |
| `destination_country` | **Yes**  | 2-letter ISO (e.g. `JP`)                                  |
| `q`                   | No       | Full-text query (Meilisearch only)                        |
| `city_id`             | No       | Filter by destination city UUID                           |
| `current_country`     | No       | 2-letter ISO — filter travelers currently in this country |
| `limit`               | No       | 1–50, default 20                                          |
| `offset`              | No       | Pagination offset, default 0                              |


**Example**

```bash
curl "http://localhost:8000/v1/travelers/search?destination_country=JP&limit=20" \
  -H "Cookie: pp_session=..."
```

**Success — 200**

```json
{
  "hits": [
    {
      "user_id": "...",
      "display_name": "Alex",
      "headline": "NRT → JFK",
      "avatar_url": null,
      "destination_country_iso": "JP",
      "destination_city_name": "Tokyo",
      "current_country_iso": "US",
      "languages": ["en"],
      "interests": ["snacks"],
      "connection_availability": "open",
      "last_active_at": "2026-06-10T03:00:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

**Search pipeline**

1. Resolve viewer's local `user_id` (excluded from results).
2. **If `MEILI_ENABLED=true` (default):**
  - Query Meilisearch index (`MEILI_TRAVELER_INDEX`, default `travelers`) with filters:
    - `destination_country`, `visibility = discoverable`, `availability != unavailable`
    - Optional `destination_city`, `current_country`
  - Hydrate hit IDs from `traveler_discovery_snapshots` via `fn_discovery_snapshots` mode 4.
3. **If Meilisearch disabled:**
  - Postgres fallback via `fn_discovery_snapshots` mode 3 (same discoverability + block rules).
4. Drop blocked pairs (`user_blocks`) and missing snapshots.
5. Map rows to `TravelerSearchResult`.

**Logs**

- `Traveler search request received`
- `Traveler search completed` (includes `hit_count`, `total`)

---

## End-to-end flows

### Flow A — Traveler becomes discoverable

```mermaid
sequenceDiagram
  participant T as Traveler client
  participant B as BFF
  participant PG as PostgreSQL
  participant M as Meilisearch

  T->>B: PATCH /v1/users/account-mode (traveler)
  T->>B: PUT /v1/travelers/profile
  B->>PG: fn_traveler_profiles + rebuild snapshot
  T->>B: POST /v1/travelers/trips
  B->>PG: fn_travel_plans + rebuild snapshot
  Note over PG,M: Outbox worker syncs snapshot to Meilisearch
  T->>B: PUT /v1/travelers/location (optional)
  B->>PG: fn_traveler_current_locations + rebuild snapshot
```



Minimum for search visibility:

- `account_mode` = `traveler`
- Profile `visibility = discoverable` and `connection_availability != unavailable`
- At least one active travel plan destination matching the searched country
- Discovery snapshot rebuilt (automatic on writes above)

### Flow B — Messenger finds travelers

```mermaid
sequenceDiagram
  participant M as Messenger client
  participant B as BFF
  participant Meili as Meilisearch
  participant PG as PostgreSQL

  M->>B: GET /v1/travelers/search?destination_country=JP
  alt Meilisearch enabled
    B->>Meili: filtered search
    B->>PG: hydrate snapshots by user ids
  else fallback
    B->>PG: fn_discovery_snapshots search
  end
  B-->>M: hits[] (excludes self + blocked users)
  M->>B: POST /v1/connections/requests (separate API)
```



Frontend: `[SearchTravelersPage](../../connect-carry/src/app/search/pages/SearchTravelersPage.tsx)` → `travelers.search()` in `[src/lib/bff.ts](../../connect-carry/src/lib/bff.ts)`.

Trip creation from UI: `[TripsPage](../../connect-carry/src/app/trips/pages/TripsPage.tsx)` → `travelers.createTrip()`.

---

## Frontend client (`connect-carry`)

The BFF wrapper lives in `src/lib/bff.ts`:


| Client method                    | HTTP                           |
| -------------------------------- | ------------------------------ |
| `travelers.getProfile()`         | `GET /v1/travelers/profile`    |
| `travelers.updateProfile(data)`  | `PUT /v1/travelers/profile`    |
| `travelers.createTrip(data)`     | `POST /v1/travelers/trips`     |
| `travelers.updateLocation(data)` | `PUT /v1/travelers/location`   |
| `travelers.search(params)`       | `GET /v1/travelers/search?...` |


Base URL: `VITE_BACKEND_URL` (default `http://localhost:8000`).

**Note:** The API search response uses `{ hits, total, limit, offset }`. Ensure the frontend client maps `hits` correctly when integrating (see `TravelerSearchResponse` in the backend schema).

---

## Configuration


| Variable               | Default                 | Purpose                                                    |
| ---------------------- | ----------------------- | ---------------------------------------------------------- |
| `MEILI_ENABLED`        | `true`                  | Use Meilisearch for search; `false` uses Postgres fallback |
| `MEILI_URL`            | `http://localhost:7700` | Meilisearch host                                           |
| `MEILI_MASTER_KEY`     | (dev key)               | API key                                                    |
| `MEILI_TRAVELER_INDEX` | `travelers`             | Index UID                                                  |


Readiness: `GET /health/ready` checks Meilisearch when enabled.

---

## Data layer reference


| Postgres function               | Mode                          | Used by         |
| ------------------------------- | ----------------------------- | --------------- |
| `fn_traveler_profiles`          | 1 get, 2 upsert+rebuild       | Profile GET/PUT |
| `fn_travel_plans`               | 2 create+destinations+rebuild | POST `/trips`   |
| `fn_traveler_current_locations` | 2 upsert+rebuild              | PUT `/location` |
| `fn_discovery_snapshots`        | 3 search, 4 fetch by ids      | GET `/search`   |


Key tables: `traveler_profiles`, `travel_plans`, `travel_plan_destinations`, `traveler_current_locations`, `traveler_discovery_snapshots`, `user_blocks`.

---

## Error quick reference


| HTTP | Typical cause                                                                    |
| ---- | -------------------------------------------------------------------------------- |
| 401  | Missing/invalid session or Bearer token                                          |
| 403  | Missing `trip:create` / `trip:join`, or messenger-only account on profile routes |
| 404  | No local `users` row, or traveler profile not created yet on GET                 |
| 422  | Validation error (invalid ISO length, empty destinations array, etc.)            |


---

## Local testing checklist

1. Start stack: Postgres, Redis, Keycloak, Meilisearch (see root [README.md](../README.md)).
2. Run migrations: `uv run python scripts/run_migrations.py`
3. Sign up / sign in as a **traveler**.
4. `PUT /profile` → `POST /trips` with `destinations[].country_iso`.
5. Sign in as a **messenger** with `trip:join`.
6. `GET /search?destination_country=<ISO>` — confirm traveler appears (may require outbox sync if Meilisearch lagging).
7. Confirm blocked users and `visibility: hidden` profiles do not appear.

---

## Related documentation

- [auth-architecture.md](./auth-architecture.md) — sessions, capabilities, account lifecycle
- [keycloak-setup-guide.md](./keycloak-setup-guide.md) — client roles (`trip:create`, `trip:join`)
- [configuration-guide.md](./configuration-guide.md) — env loading
- [README.md](../README.md) — full API index and middleware order
