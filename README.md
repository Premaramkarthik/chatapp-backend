<p align="center">
  <h1 align="center">PariPath ChatApp Backend</h1>
  <p align="center">
    A production-grade social discovery and real-time messaging platform backend built with FastAPI, Keycloak, Tinode, PostgreSQL, Redis, and Meilisearch.
  </p>
</p>

---

## Table of Contents

- [Project Overview](#project-overview)
- [Technology Stack](#technology-stack)
- [High-Level Architecture](#high-level-architecture)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Configuration Reference](#configuration-reference)
- [Database Layer](#database-layer)
- [API Reference](#api-reference)
- [Authentication & Authorization](#authentication--authorization)
- [Business Domains](#business-domains)
- [Infrastructure Adapters](#infrastructure-adapters)
- [Middleware Pipeline](#middleware-pipeline)
- [Background Workers](#background-workers)
- [Observability](#observability)
- [Testing](#testing)
- [Deployment](#deployment)
- [Security Considerations](#security-considerations)
- [Contributing](#contributing)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Project Overview

PariPath ChatApp is a **traveler-discovery and messaging platform** that connects travelers heading to the same destinations. The backend orchestrates:

- **User lifecycle** — Email/social signup → verification → profile setup → active account
- **Traveler discovery** — Full-text + geo-filtered search of discoverable traveler profiles
- **Connection matching** — Mutual-accept connection requests with expiry and blocking
- **Real-time chat** — P2P conversations via Tinode with backend-managed topic provisioning
- **BFF authentication** — Secure cookie-based sessions with OAuth2 PKCE via Keycloak

### Key Workflows

```
Signup → Keycloak Account → Email Verification → Profile Setup → Search Travelers
  → Send Connection Request → Mutual Accept → Provision Tinode Topic → Chat
```

---

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Runtime** | Python 3.13, FastAPI, Uvicorn | Async HTTP API server |
| **Package Manager** | `uv` | Dependency management & lockfile |
| **Identity Provider** | Keycloak 26 | OAuth2/OIDC, user management, social login |
| **Database** | PostgreSQL 17 (asyncpg) | Primary data store with stored functions |
| **Cache / Rate Limiting** | Redis 7 | Session cache, JWKS cache, rate counters |
| **Search** | Meilisearch 1.13 | Traveler discovery full-text search |
| **Chat Engine** | Tinode (gRPC + REST) | Real-time P2P messaging |
| **Logging** | Loguru | Structured console + rotating file logs |
| **Metrics** | Custom Prometheus registry | HTTP & application metrics |
| **Containerization** | Docker, Docker Compose | Full local development stack |
| **Code Quality** | Ruff, Black, pre-commit | Linting and formatting |
| **Testing** | pytest, pytest-asyncio, httpx | Async unit and integration tests |

---

## High-Level Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────────────────┐
│   Client    │────▶│                  FastAPI Backend                     │
│  (Web/App)  │◀────│                                                      │
└─────────────┘     │  ┌─────────────┐  ┌───────────┐  ┌───────────────┐  │
                    │  │  Middleware  │  │  Routers  │  │  Dependencies │  │
                    │  │  Pipeline   │──▶│  (v1/*)   │──▶│  (DI/Auth)    │  │
                    │  └─────────────┘  └───────────┘  └───────────────┘  │
                    │         │               │               │            │
                    │         ▼               ▼               ▼            │
                    │  ┌─────────────────────────────────────────────┐     │
                    │  │              Domain Services                 │     │
                    │  │   Auth · Users · Chat · Matching · Search   │     │
                    │  └─────────────────────────────────────────────┘     │
                    │                        │                             │
                    │         ┌───────────────┼────────────────┐           │
                    │         ▼               ▼                ▼           │
                    │  ┌───────────┐  ┌────────────┐  ┌──────────────┐    │
                    │  │ PostgreSQL│  │   Redis     │  │  Keycloak    │    │
                    │  │ (asyncpg) │  │  (cache)    │  │  (OIDC/JWT)  │    │
                    │  └───────────┘  └────────────┘  └──────────────┘    │
                    │         │                                            │
                    │         ▼                                            │
                    │  ┌───────────┐  ┌────────────┐                      │
                    │  │Meilisearch│  │   Tinode    │                      │
                    │  │ (search)  │  │  (gRPC/WS)  │                      │
                    │  └───────────┘  └────────────┘                      │
                    └──────────────────────────────────────────────────────┘
```

The system follows **Clean Architecture** with clear separation:
- **`core/`** — Settings, logging, observability (no business logic)
- **`domains/`** — Business logic and service orchestration
- **`infrastructure/`** — External adapter implementations (Postgres, Redis, Keycloak, Tinode, Meilisearch)
- **`v1/`** — HTTP API layer (routers, middleware, schemas, dependencies)

---

## Project Structure

```
chatapp-backend/
├── main.py                         # Application factory & lifespan
├── pyproject.toml                  # Dependencies (uv)
├── Dockerfile                      # Production container
├── docker-compose.yml              # Full dev stack (9 services)
├── .env.example                    # Environment variable reference
├── .pre-commit-config.yaml         # Code quality hooks
│
├── core/                           # Cross-cutting concerns
│   ├── config/settings.py          # Pydantic settings (env-driven)
│   ├── logging/logger.py           # Loguru setup
│   └── observability/metrics.py    # Prometheus-compatible registry
│
├── domains/                        # Business logic (no framework deps)
│   ├── auth/                       # Auth service, session resolver, signup security
│   ├── users/                      # User entity, repository port, bootstrap use case
│   ├── chat/                       # Tinode provisioning, session builder
│   ├── matching/                   # Connection policies
│   └── search/                     # Outbox worker for Meilisearch sync
│
├── infrastructure/                 # Adapter implementations
│   ├── database/                   # asyncpg pool, stored-function helpers, repositories
│   ├── keycloak/                   # JWT verifier, OIDC adapter
│   ├── redis/                      # Cache facade with in-memory fallback
│   ├── tinode/                     # gRPC client, REST auth handler
│   └── meilisearch/                # Client, search, sync, health
│
├── v1/                             # API version 1
│   ├── routers/                    # auth, users, travelers, connections, chat, health, internal
│   ├── middleware/                  # Auth, CSRF, rate limit, security headers, logging, DB session
│   ├── dependencies/               # DI factories, auth extractors
│   ├── schemas/                    # Pydantic request/response models
│   └── utils/                      # Exception hierarchy
│
├── migrations/                     # Idempotent SQL migrations (001–007); see docs/migrations/
├── scripts/                        # Migration runner, commit validator
└── tests/                          # pytest-asyncio test suite
```

---

## Getting Started

### Prerequisites

- **Docker** ≥ 24.0 and **Docker Compose** ≥ 2.20
- **Python** ≥ 3.13 (for local dev without Docker)
- **uv** package manager (`pip install uv`)

### Quick Start (Docker)

```bash
# 1. Clone and configure
git clone <repo-url> && cd chatapp-backend
cp .env.example .env   # Edit secrets for local dev

# 2. Launch full stack (Postgres, Redis, Keycloak, Tinode, Meilisearch)
docker compose up -d

# 3. One-time Keycloak setup (realm, clients, roles) — see docs/keycloak-setup-guide.md
#    Startup validation will fail until chatapp-web, chatapp-api, and service account are configured.

# 4. Optional: configure Keycloak SMTP (ops script, not required at runtime)
uv run python scripts/configure_keycloak_smtp.py

# 5. Run database migrations
uv run python scripts/run_migrations.py

# 6. Start the API server
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Local Development (without Docker)

```bash
uv sync                    # Install dependencies
uv run uvicorn main:app --reload
```

### Verify Installation

```bash
curl http://localhost:8000/health/live     # → {"status": "ok"}
curl http://localhost:8000/health/ready    # → checks all dependencies
```

### Development Tools

| URL | Service |
|---|---|
| `http://localhost:8000/docs` | Swagger UI |
| `http://localhost:8000/redoc` | ReDoc |
| `http://localhost:8180` | Keycloak Admin Console |
| `http://localhost:8081` | Adminer (with `--profile tools`) |
| `http://localhost:7700` | Meilisearch Dashboard |

---

## Configuration Reference

Non-sensitive defaults live in [`config.yaml`](config.yaml). Secrets and connection URLs belong in `.env`. Environment variables override YAML. See [`docs/configuration-guide.md`](docs/configuration-guide.md) and `.env.example`.

### Critical Variables

| Variable | Required | Description |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | ✅ | PostgreSQL connection |
| `DB_POOL_AUTO` | — | Auto-size pool based on `max_connections` |
| `KEYCLOAK_BASE_URL`, `KEYCLOAK_REALM` | ✅ | Identity provider |
| `KEYCLOAK_WEB_CLIENT_SECRET` | ✅ | OIDC client secret |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | ✅ | Admin API client secret |
| `AUTH_TOKEN_ENCRYPTION_KEY` | ✅ | Fernet key for token encryption at rest |
| `AUTH_COOKIE_SECURE` | — | `true` in production |
| `REDIS_URL` | ✅ | Redis connection string |
| `TINODE_REST_AUTH_SHARED_SECRET` | ✅ | Shared secret for Tinode ↔ API auth |
| `TINODE_GRPC_HOST` | ✅ | Tinode gRPC endpoint |
| `MEILI_MASTER_KEY` | ✅ | Meilisearch admin key |

### Pool Auto-Sizing

When `DB_POOL_AUTO=true`, the system queries PostgreSQL `max_connections` at startup and calculates:

```
max_size = min(floor(max_connections / concurrent_requests), ceiling)
min_size = max(1, max_size // 4)
```

---

## Database Layer

### Schema Management

Migrations are **idempotent SQL files** in `migrations/` applied in filename order via `scripts/run_migrations.py`. A `schema_migrations` table tracks applied files with SHA-256 checksums to detect drift.

```bash
uv run python scripts/run_migrations.py              # Apply pending
uv run python scripts/run_migrations.py --database-url "postgres://..."  # Override DSN
```

Audit notes, dependency graph, and deployment guidance: [`docs/migrations/`](docs/migrations/).

**Existing databases** that applied the legacy 15-file chain must be re-baselined before running the consolidated files — see [`docs/migrations/deployment-risk.md`](docs/migrations/deployment-risk.md).

### Migration Inventory

| File | Layer |
|---|---|
| `001_extensions.sql` | `pgcrypto`, `pg_trgm` |
| `002_tables.sql` | 23 tables, indexes, constraints (final shape) |
| `003_functions_core.sql` | `fn_users` (modes 1–14), `fn_signup_sessions`, `fn_tinode_user_mappings`, `fn_health`, `set_updated_at` |
| `004_functions_social.sql` | Social/discovery/connection/travel/outbox `fn_*` helpers |
| `005_functions_chat.sql` | `fn_tinode_conversation_mappings` (modes 1–5) |
| `006_triggers.sql` | 10 `updated_at` triggers |
| `007_seeds_geo.sql` | Geo reference seed data |

### Stored Functions

Business-critical operations use **mode-based JSONB stored functions** for atomic, consistent database interactions:

- **`fn_users(mode, payload)`** — signup create (7), Keycloak relink (8), activate after verified signin (10), profile complete (12), onboarding step (13), delete by sub (14)
- **`fn_tinode_user_mappings(mode, payload)`** — Upsert and lookup Tinode user links
- **`fn_tinode_conversation_mappings(mode, payload)`** — Provision, inbox list, update, archive
- **`fn_health(mode, payload)`** — Database liveness probe

### Connection Pool

Built on `asyncpg` with:
- Per-event-loop pool isolation (safe for multi-loop test scenarios)
- Exponential backoff retry on transient connection errors
- JSON/JSONB codec auto-configuration
- Instrumented acquire timing

---

## API Reference

### Authentication (`/v1/auth`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/auth/signup/start` | Public | Step 1: email + password (requires `Idempotency-Key`) |
| `POST` | `/v1/auth/signup/complete` | Public | Step 2: display name + account mode |
| `POST` | `/v1/auth/signup` | Public | **Deprecated** — returns `410 Gone` |
| `POST` | `/v1/auth/signup/resend` | Public | Resend verification email |
| `POST` | `/v1/auth/signup/social/start` | Public | Begin Google/Apple social signup |
| `POST` | `/v1/auth/signin/start` | Public | Begin PKCE authorization flow |
| `GET` | `/v1/auth/signin/callback` | Public | Complete OAuth callback, set cookies |
| `POST` | `/v1/auth/logout` | Session | Revoke session, clear cookies |
| `POST` | `/v1/auth/forgot-password` | Public | Trigger Keycloak password reset |
| `GET` | `/v1/auth/sessions` | Session + `session:manage` | List active sessions |
| `DELETE` | `/v1/auth/sessions/{id}` | Session + `session:manage` | Revoke specific session |
| `DELETE` | `/v1/auth/sessions/all` | Session + `session:manage` | Revoke all sessions |

### Users (`/v1`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/me` | Bearer/Session | Get or bootstrap current user |
| `PATCH` | `/me/account-mode` | `profile:update` | Update account mode (traveler/messenger/both) |

### Travelers (`/v1/travelers`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/profile` | Bearer | Get traveler profile |
| `PUT` | `/profile` | `trip:create` | Upsert traveler profile |
| `POST` | `/trips` | `trip:create` | Create travel plan with destinations |
| `PUT` | `/location` | `trip:create` | Update current location |
| `GET` | `/search` | `trip:join` | Search travelers by destination |

### Connections (`/v1/connections`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/requests` | `message:send` | Send connection request |
| `GET` | `/requests/incoming` | `message:send` | List pending incoming requests |
| `POST` | `/requests/{id}/accept` | `message:send` | Accept request (creates connection) |
| `POST` | `/requests/{id}/reject` | `message:send` | Reject request |

### Chat (`/v1/chat`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/tinode-session` | Bearer | Get Tinode WebSocket login secret |
| `GET` | `/inbox` | `message:send` | List chat-eligible connections |
| `GET` | `/conversations/{id}` | `message:send` | Get Tinode mapping for connection |
| `POST` | `/conversations` | `message:create-room` | Provision Tinode P2P topic |
| `POST` | `/conversations/{id}/archive` | `message:send` | Archive conversation |

### System

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness (DB + Keycloak + Meilisearch + Tinode) |
| `GET` | `/v1/system/version` | App name, version, environment |
| `GET` | `/metrics` | Prometheus text exposition |
| `POST` | `/internal/tinode/auth` | Tinode REST authenticator callback (service-to-service) |

---

## Authentication & Authorization

### BFF (Backend-for-Frontend) Pattern

The system implements a **cookie-based BFF session layer** on top of Keycloak:

1. **Signup** — Local `pending_verification` user created → Keycloak account provisioned → verification email sent → profile completed via `/signup/complete`
2. **Email verification** — User clicks the Keycloak verification link (updates Keycloak only; Postgres is unchanged until sign-in or reconciliation)
3. **Account activation** — User completes OAuth sign-in via `POST /v1/auth/signin/start` → `GET /v1/auth/signin/callback`; the callback reads `email_verified` from the access token and runs `fn_users` mode 10 to set `email_verified=true` and transition status to `active` (or `pending_profile_setup` when applicable)
4. **Signin** — PKCE Authorization Code flow initiated → callback exchanges code for tokens → encrypted session created → `HttpOnly` cookie set
5. **Session resolution** — Middleware extracts session cookie → decrypts tokens from DB/cache → verifies JWT → attaches principal to request state
6. **Token refresh** — Automatic transparent refresh when access token is near expiry (`AUTH_REFRESH_LEEWAY_SEC`)

**Important:** Clicking the verification email link alone does not activate the local account. Users must sign in after verifying email. A background reconciliation job (`AUTH_VERIFICATION_RECONCILE_*`) can activate users who verified in Keycloak but have not signed in yet, as a safety net.

The `chatapp-web` client includes an `email_verified` protocol mapper so the access token carries the claim required for activation at sign-in.

### Security Controls

- **Token encryption at rest** — All OAuth tokens encrypted with `cryptography.fernet` before DB storage
- **Session hashing** — Session tokens stored as SHA-256 hashes (never plaintext)
- **CSRF protection** — Double-submit cookie pattern for all unsafe methods
- **Rate limiting** — Redis-backed (or in-memory) per-IP sliding window
- **Signup abuse prevention** — Multi-key rate limits on IP, device fingerprint, email domain
- **Idempotency** — Signup requests require `Idempotency-Key` header for exactly-once semantics
- **Capability-based authorization** — Roles extracted from Keycloak JWT (`profile:update`, `message:send`, `trip:create`, etc.)
- **Security event logging** — `auth_security_events` table records login anomalies

### Middleware Execution Order (outermost → innermost)

```
Request → RequestId → SecurityHeaders → CORS → ErrorHandling → Logging
  → RateLimit → DatabaseSession → CSRF → JWTAuthentication → Router
```

---

## Business Domains

### Auth Domain (`domains/auth/`)

Core orchestration for the entire authentication lifecycle:
- `AuthService` — Signup, signin, callback, logout, session management
- `AuthSessionResolver` — Cookie → principal resolution with cache-ahead
- `signup_security` — Redis-based multi-key rate limiting for signup abuse prevention
- `KeycloakAuthClient` — Admin API interactions (user creation, email triggers, role assignment)

### Users Domain (`domains/users/`)

- `User` dataclass — Immutable domain entity with lifecycle states (`pending_verification` → `active`)
- `UserRepository` protocol — Persistence port with 8 operations
- `BootstrapUser` use case — Idempotent user creation on first authenticated access
- `AccountMode` enum — `traveler`, `messenger`, `both`

### Chat Domain (`domains/chat/`)

- `provision_conversation_for_connection()` — Creates Tinode P2P topic mapping between connected users
- `build_tinode_session()` — Generates base64 login secrets for client-side Tinode WebSocket auth
- Auto-provision on connection accept (configurable via `TINODE_AUTO_PROVISION_ON_ACCEPT`)

### Matching Domain (`domains/matching/`)

Product rules for traveler discovery:
- Mutual accept required before connections
- Connection requests expire after 14 days (checked on read)
- Users with `account_mode=both` can search and be discovered

### Search Domain (`domains/search/`)

Outbox worker that syncs `traveler_discovery_snapshots` to Meilisearch in batches of 50.

---

## Infrastructure Adapters

### PostgreSQL (`infrastructure/database/`)

- **Connection pool** — `asyncpg.Pool` with per-event-loop isolation, auto-sizing, and retry
- **Stored function gateway** — `call_json_function(name, mode, payload)` for all DB operations
- **Repositories** — `PostgresUserRepository`, `PostgresAuthRepository`, `PostgresMatchingRepository`, `PostgresConversationRepository`, `PostgresDiscoveryRepository`, `PostgresTravelerRepository`, `PostgresTripRepository`

### Redis (`infrastructure/redis/`)

- `AuthRedisCache` — JSON/string cache facade with automatic in-memory fallback on Redis failure
- Used for: session cache, JWKS cache, rate limit counters, idempotency keys, revocation checks

### Keycloak (`infrastructure/keycloak/`)

- `KeycloakVerifier` — JWKS verification with Redis cache and stale fallback
- `KeycloakAdminClient` — Admin REST for user CRUD, email actions, role management
- `KeycloakAuthClient` — OIDC flows (auth code, refresh, password grant)
- `startup_validation` — fail-fast checks when `KEYCLOAK_ENABLED=true`

Setup: [`docs/keycloak-setup-guide.md`](docs/keycloak-setup-guide.md). Migration: [`docs/keycloak-migration-checklist.md`](docs/keycloak-migration-checklist.md).
- Health check via OIDC discovery endpoint

### Tinode (`infrastructure/tinode/`)

- **gRPC client** — `prepare_p2p_conversation()` creates P2P topics via Tinode's plugin API
- **REST auth handler** — Callback endpoint for Tinode's REST authenticator (`/internal/tinode/auth`)
- Supports `auth`, `link`, `rtagns`, and `checkunique` endpoints

### Meilisearch (`infrastructure/meilisearch/`)

- Lazy singleton client via `@lru_cache`
- `search_travelers()` — Filtered search by destination country, current country, city
- `upsert_traveler()` / `delete_traveler()` — Document sync operations
- Postgres fallback when `MEILI_ENABLED=false`

---

## Background Workers

### Search Outbox Worker

The `run_search_outbox_loop()` runs as a background `asyncio.Task` during app lifespan:

1. Claims a batch of pending `search_outbox_events`
2. For each event: upserts or deletes the corresponding Meilisearch document
3. Marks events as `completed` or `failed` with error details
4. Sleeps `interval_sec` (default 5s) when idle

This implements the **Transactional Outbox pattern** ensuring eventual consistency between Postgres and Meilisearch.

---

## Observability

### Stack

| Component | Purpose |
|-----------|---------|
| **Loguru + JSON** | Structured logs with `trace_id`, `request_id`, `correlation_id` |
| **Prometheus** | Metrics via `prometheus-client` + `prometheus-fastapi-instrumentator` |
| **OpenTelemetry** | Traces exported to Tempo (OTLP gRPC) |
| **Grafana** | Dashboards linking metrics, logs, and traces |

Start the observability profile (API must be running on host port 8000 for Prometheus scrape):

```bash
docker compose --profile observability up -d prometheus grafana loki promtail tempo cadvisor
```

| Service | URL |
|---------|-----|
| Grafana | http://localhost:3001 (admin / admin) |
| Prometheus | http://localhost:9090 |
| Tempo | OTLP gRPC localhost:4317 |
| Loki | http://localhost:3100 |

Configure the API for tracing:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=chatapp-backend
OTEL_TRACES_SAMPLER_ARG=0.1   # production: lower sample rate
```

### Logging

- **Library**: Loguru with human-readable lines in console and `logs/backend.log`
- **File**: Rotating 100MB files, 30-day retention at `logs/backend.log`
- **Correlation**: `X-Request-ID` and optional `X-Correlation-ID` headers
- **Trace linking**: OpenTelemetry injects `trace_id` / `span_id` into every log line

### Metrics (`/metrics`)

Prometheus exposition includes HTTP metrics (Instrumentator), auth counters (`signup_success_total`, `login_failure_total`), database histograms (`database_query_duration_seconds`), Keycloak metrics, and pool gauges.

Example queries in Grafana or Prometheus:

```promql
rate(login_success_total[5m])
histogram_quantile(0.95, sum(rate(database_query_duration_seconds_bucket[5m])) by (le))
pending_verifications
```

Search logs by trace ID in Loki:

```logql
{job="chatapp-backend"} | json | trace_id="<trace-id-from-grafana>"
```

### Health Checks

- **`/health/live`** — Always returns `{"status": "ok"}` (liveness)
- **`/health/ready`** — Checks Database, Keycloak, Meilisearch, Tinode (readiness, returns 503 if degraded)

---

## Testing

```bash
uv run pytest                       # Run all tests
uv run pytest -x                    # Stop on first failure
uv run pytest --tb=short -q         # Compact output
```

Test configuration (`tests/conftest.py`) automatically disables external integrations:

```python
KEYCLOAK_ENABLED=false
TINODE_ENABLED=false
MEILI_ENABLED=false
REDIS_ENABLED=false
```

### Code Quality

```bash
pre-commit install                  # Install git hooks
pre-commit run --all-files          # Manual run

uv run ruff check .                 # Lint
uv run black --check .              # Format check
```

Conventional commit messages are enforced via `scripts/validate_commit_msg.py`.

---

## Deployment

### Docker Production Build

```bash
docker build -t chatapp-backend .
docker run -p 8000:8000 --env-file .env chatapp-backend
```

The Dockerfile uses `ghcr.io/astral-sh/uv:python3.13-bookworm` with:
- `UV_COMPILE_BYTECODE=1` for faster cold starts
- Frozen lockfile install (`--no-dev`)
- Uvicorn as the ASGI server

### Docker Compose (Development)

The `docker-compose.yml` orchestrates **8 services**:

| Service | Port | Purpose |
|---|---|---|
| `postgres` | 5433 | Primary database |
| `redis` | 6379 | Cache and rate limiting |
| `keycloak` | 8180 | Identity provider |
| `tinode` | 6060 / 16060 | Chat engine (HTTP + gRPC) |
| `meilisearch` | 7700 | Search engine |
| `api` | 8000 | FastAPI application |
| `adminer` | 8081 | Database administration (`docker compose --profile tools up`) |
| `tinode-init` | — | One-shot Tinode bootstrapper |

### Production Checklist

- [ ] Set strong values for `AUTH_TOKEN_ENCRYPTION_KEY`, `TINODE_REST_AUTH_SHARED_SECRET`, all `*_SECRET` vars
- [ ] Set `AUTH_COOKIE_SECURE=true` and `AUTH_COOKIE_SAMESITE=strict`
- [ ] Set `APP_DEBUG=false` and `APP_ENV=production`
- [ ] Configure `DB_POOL_AUTO=true` or tune `DB_POOL_MIN`/`DB_POOL_MAX`
- [ ] Set `TINODE_AUTH_ALLOW_PLAINTEXT_DEV_SECRET=false`
- [ ] Configure `AUTH_CAPTCHA_REQUIRED=true` for signup abuse protection
- [ ] Set `MIDDLEWARE_CORS_ORIGINS` to production domains only
- [ ] Mount persistent volumes for Postgres, Redis, Meilisearch data
- [ ] Set up Prometheus scraping of `/metrics` endpoint

---

## Security Considerations

### Data Protection

- OAuth tokens encrypted with Fernet before database storage
- Session tokens stored as SHA-256 hashes
- Signup passwords validated server-side and set in Keycloak via Admin API; never stored in the app database
- PII fields (email, IP, user-agent) hashed in security event logs

### Attack Surface Mitigation

- **CSRF**: Double-submit cookie pattern on all state-changing requests
- **XSS**: `Content-Security-Policy`, `X-Content-Type-Options: nosniff`
- **Clickjacking**: `X-Frame-Options: DENY`
- **HSTS**: `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- **Rate limiting**: Per-IP + per-path with Redis-backed counters
- **Signup abuse**: Multi-vector rate limits (IP, device fingerprint, email domain)
- **Blocked email domains**: Configurable deny-list for disposable email providers

### Exception Hierarchy

Centralized in `v1/utils/base.py`:

```
AppError
├── ConfigurationError
├── DatabaseError
│   ├── DatabaseConnectionError
│   └── MigrationError
├── AuthenticationError
├── AuthorizationError
└── IntegrationError
    ├── KeycloakIntegrationError
    ├── MeilisearchIntegrationError
    └── TinodeIntegrationError
        └── TinodeAuthError
```

---

## Contributing

1. Fork the repository and create a feature branch
2. Install pre-commit hooks: `pre-commit install`
3. Follow conventional commit format: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
4. Ensure all tests pass: `uv run pytest`
5. Ensure code quality: `pre-commit run --all-files`
6. Submit a pull request with a clear description

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `DatabaseConnectionError` on startup | Verify Postgres is running and `DB_*` env vars are correct |
| `TooManyConnectionsError` | Enable `DB_POOL_AUTO=true` or reduce `DB_POOL_MAX` |
| Keycloak health check fails | Complete one-time setup in `docs/keycloak-setup-guide.md`; check startup validation logs |
| Redis fallback warnings in logs | Check Redis connectivity; the system degrades gracefully to in-memory |
| Tinode provision fails | Verify both users have completed Tinode link (`fn_tinode_user_mappings`) |
| Meilisearch search returns empty | Check outbox worker is running; verify `MEILI_ENABLED=true` |
| CSRF token errors | Ensure client sends `X-CSRF-Token` header matching `pp_csrf` cookie |
| Migration checksum mismatch | A previously applied migration file was modified — restore original or reset dev DB (`DELETE FROM schema_migrations WHERE filename IN (...)` then re-run migrations) |
| Keycloak signup emails not sent | Run `uv run python scripts/configure_keycloak_smtp.py --test` with Gmail App Password in `.env` |
| Gmail SMTP auth failures | Use a 16-character App Password with 2-Step Verification enabled; port 587 + STARTTLS |

---

## License

Proprietary. All rights reserved.
