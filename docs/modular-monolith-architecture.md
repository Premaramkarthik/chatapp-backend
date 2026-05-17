# Modular Monolith Architecture

This document defines the target architecture for the current FastAPI backend after renaming the root application package to `chatapp_backend/`.

The target is a production-grade modular monolith. It keeps one deployable Python service, but organizes code by explicit business and infrastructure boundaries so future extraction to workers or microservices remains possible.

## Architectural Intent

The backend uses:

- Clean Architecture for dependency direction.
- Hexagonal Architecture for ports and adapters.
- Domain-oriented module boundaries.
- Async-first FastAPI and asyncpg.
- Replaceable infrastructure integrations.
- Production operational standards for health, logging, metrics, tracing, testing, and deployments.

The refactor must preserve existing behavior first. Do not add new product features while moving code.

## Updated Folder Structure

```text
chatapp-backend/
├── chatapp_backend/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── routers/
│   │       │   ├── __init__.py
│   │       │   ├── health.py
│   │       │   ├── users.py
│   │       │   └── internal.py
│   │       ├── schemas/
│   │       │   ├── __init__.py
│   │       │   ├── auth.py
│   │       │   ├── common.py
│   │       │   └── users.py
│   │       ├── dependencies/
│   │       │   ├── __init__.py
│   │       │   ├── auth.py
│   │       │   ├── container.py
│   │       │   └── database.py
│   │       └── responses/
│   │           ├── __init__.py
│   │           └── errors.py
│   │
│   ├── domains/
│   │   ├── __init__.py
│   │   ├── users/
│   │   │   ├── __init__.py
│   │   │   ├── entities/
│   │   │   │   ├── __init__.py
│   │   │   │   └── user.py
│   │   │   ├── repositories/
│   │   │   │   ├── __init__.py
│   │   │   │   └── user_repository.py
│   │   │   ├── use_cases/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── bootstrap_user.py
│   │   │   │   └── get_current_user.py
│   │   │   ├── schemas/
│   │   │   │   ├── __init__.py
│   │   │   │   └── commands.py
│   │   │   ├── exceptions/
│   │   │   │   ├── __init__.py
│   │   │   │   └── users.py
│   │   │   └── interfaces/
│   │   │       ├── __init__.py
│   │   │       └── identity_provider.py
│   │   │
│   │   ├── chat/
│   │   │   ├── __init__.py
│   │   │   ├── entities/
│   │   │   ├── repositories/
│   │   │   ├── use_cases/
│   │   │   ├── schemas/
│   │   │   ├── exceptions/
│   │   │   └── interfaces/
│   │   │       ├── __init__.py
│   │   │       ├── chat_gateway.py
│   │   │       ├── message_publisher.py
│   │   │       └── presence_gateway.py
│   │   │
│   │   ├── travelers/
│   │   ├── trips/
│   │   ├── matching/
│   │   ├── moderation/
│   │   └── notifications/
│   │
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── database/
│   │   │   ├── __init__.py
│   │   │   ├── connection/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── pool.py
│   │   │   │   ├── pool_instrumentation.py
│   │   │   │   ├── pool_sizing.py
│   │   │   │   └── transaction.py
│   │   │   ├── repositories/
│   │   │   │   ├── __init__.py
│   │   │   │   └── users.py
│   │   │   └── postgres/
│   │   │       ├── __init__.py
│   │   │       └── executor.py
│   │   ├── keycloak/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py
│   │   │   ├── health.py
│   │   │   └── jwks.py
│   │   ├── tinode/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py
│   │   │   ├── health.py
│   │   │   └── rest_auth.py
│   │   ├── meilisearch/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py
│   │   │   └── health.py
│   │   ├── redis/
│   │   │   └── __init__.py
│   │   └── storage/
│   │       └── __init__.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   └── settings.py
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── authentication.py
│   │   │   ├── cors.py
│   │   │   ├── database.py
│   │   │   ├── error_handling.py
│   │   │   ├── logging.py
│   │   │   ├── rate_limit.py
│   │   │   ├── request_id.py
│   │   │   └── state.py
│   │   ├── logging/
│   │   │   ├── __init__.py
│   │   │   └── logger.py
│   │   ├── observability/
│   │   │   ├── __init__.py
│   │   │   ├── health.py
│   │   │   ├── metrics.py
│   │   │   └── tracing.py
│   │   ├── security/
│   │   │   ├── __init__.py
│   │   │   └── principals.py
│   │   └── exceptions/
│   │       ├── __init__.py
│   │       └── base.py
│   │
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── utils/
│   │   │   └── __init__.py
│   │   ├── constants/
│   │   │   └── __init__.py
│   │   ├── enums/
│   │   │   └── __init__.py
│   │   └── helpers/
│   │       └── __init__.py
│   │
│   └── tests/
│       ├── unit/
│       ├── api/
│       ├── integration/
│       └── contracts/
│
├── migrations/
├── scripts/
├── docker/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
└── README.md
```

Notes:

- `chatapp_backend/main.py` becomes the ASGI app factory module.
- Root `main.py` can remain temporarily as a compatibility shim importing `main:app`.
- Docker, migrations, and scripts stay at repository root.
- Tests may remain root-level during migration if tooling becomes simpler, but the target package ownership should be reflected in test folder names.
- Future domain folders may start with only boundary docs and `__init__.py`; do not add business code until the feature exists.

## Migration And Refactor Plan

### Phase 0: Safety Baseline

- Freeze current behavior with tests.
- Confirm `uv run ruff check .`, `uv run black --check .`, and `uv run pytest`.
- Confirm Docker Compose config and startup remain valid.
- Do not change SQL behavior during package moves.

### Phase 1: Package Rename

- Create `chatapp_backend/`.
- Move existing root-level `core/` into `chatapp_backend/core/`.
- Move existing root-level `infrastructure/` into `chatapp_backend/infrastructure/`.
- Move `v1/app.py` into `chatapp_backend/main.py`.
- Keep root `main.py` as:

```python
from main import app
```

- Update imports from `core.*` to `core.*`.
- Update imports from `infrastructure.*` to `infrastructure.*`.
- Update Dockerfile and Uvicorn command only if the shim is removed.

### Phase 2: API Boundary

- Create `chatapp_backend/api/v1`.
- Move `v1/routers` to `chatapp_backend/api/v1/routers`.
- Move `v1/models` to `chatapp_backend/api/v1/schemas`.
- Replace ambiguous `models` with explicit API schema modules.
- Keep API schemas focused on HTTP request/response contracts.
- Remove direct infrastructure imports from routers.

### Phase 3: Infrastructure Adapters

- Move `v1/services/keycloak.py` to `chatapp_backend/infrastructure/keycloak/adapter.py`.
- Move `v1/services/tinode_auth.py` to `chatapp_backend/infrastructure/tinode/rest_auth.py`.
- Move `v1/services/meilisearch.py` to `chatapp_backend/infrastructure/meilisearch/health.py` or `adapter.py`.
- Keep provider-specific DTO mapping in infrastructure.
- Translate provider errors into core or domain exceptions.

### Phase 4: Users Domain

- Create `chatapp_backend/domains/users`.
- Add `User` entity.
- Add `BootstrapUserCommand`.
- Add `UserRepository` port.
- Add `BootstrapUser` use case.
- Move user bootstrap logic out of `v1/services/users.py`.
- Add `PostgresUserRepository` in `chatapp_backend/infrastructure/database/repositories/users.py`.

### Phase 5: Chat Domain

- Create `chatapp_backend/domains/chat`.
- Define Tinode-independent ports:
  - `ChatGateway`
  - `PresenceGateway`
  - `MessagePublisher`
- Keep Tinode REST-auth request/response details in `infrastructure/tinode`.
- Add only the chat domain abstractions needed by the existing Tinode callback.

### Phase 6: Remove Legacy `v1/services`

- Replace all imports from `v1.services`.
- Delete `v1/services`.
- Keep only `chatapp_backend/api/v1` for HTTP v1.
- Confirm no `v1` imports remain except transitional compatibility shims.

### Phase 7: Observability

- Add `chatapp_backend/core/observability/metrics.py`.
- Add Prometheus-compatible metrics endpoint or instrumented ASGI middleware.
- Add no-op metric interfaces first if runtime dependency risk is high.
- Track request count, latency, error count, DB acquire wait, provider latency, and rate-limit blocks.

### Phase 8: Future-Ready Infrastructure

- Add `redis/` only when needed for distributed rate limiting, websocket presence, or background jobs.
- Add `storage/` only when file-sharing implementation starts.
- Add background worker package only when outbox or async delivery is required.

## Dependency Flow Rules

Dependency direction:

```text
api.v1
  -> domains
  -> domain ports/interfaces

infrastructure
  -> domain ports/interfaces
  -> core config/logging/exceptions

core
  -> no domain business logic

domains
  -> shared primitives
  -> standard library
```

Allowed imports:

| From | May import |
| --- | --- |
| `api/v1` | domain use cases, API schemas, API dependencies, core HTTP helpers |
| `domains/*` | same domain, shared primitives, standard library |
| `infrastructure/*` | domain interfaces, domain entities/schemas, core config/logging, external SDKs |
| `core/*` | config, middleware, logging, observability, security primitives |
| `shared/*` | standard library and stable local primitives |

Forbidden imports:

| Location | Must not import |
| --- | --- |
| `domains/*` | FastAPI, asyncpg, httpx, Tinode, Meilisearch, Redis, Keycloak SDKs |
| `api/v1/*` | asyncpg, raw SQL, Tinode client, Meilisearch client |
| `core/middleware/*` | domain use cases or business services |
| `shared/*` | FastAPI, asyncpg, provider clients |

## Domain Boundary Rules

### Users

Owns:

- local application user
- Keycloak subject mapping as a business identity value
- user status and lifecycle rules
- user bootstrap use cases

Does not own:

- JWT decoding
- Keycloak JWKS behavior
- SQL implementation
- HTTP request/response schemas

### Chat

Owns:

- chat identity abstraction
- conversation eligibility rules
- chat-facing ports

Does not own:

- Tinode REST-auth payload shape
- Tinode gRPC or HTTP clients
- WebSocket scale-out infrastructure

### Travelers, Trips, Matching, Moderation, Notifications

These are target domain boundaries. Create real entities and use cases only when their product work begins. Until then, keep them empty or documented only.

## Example Domain Implementation

### Entity

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    identity_subject: str
    email: str | None
    display_name: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    def is_active(self) -> bool:
        return self.status == "active"
```

### Command

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BootstrapUserCommand:
    identity_subject: str
    email: str | None
    display_name: str | None
```

### Repository Port

```python
from typing import Protocol


class UserRepository(Protocol):
    async def get_by_identity_subject(self, subject: str) -> User | None:
        ...

    async def create_from_identity(self, command: BootstrapUserCommand) -> User:
        ...
```

### Use Case

```python
class BootstrapUser:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, command: BootstrapUserCommand) -> User:
        existing = await self._users.get_by_identity_subject(command.identity_subject)
        if existing is not None:
            return existing
        return await self._users.create_from_identity(command)
```

The use case imports no FastAPI, asyncpg, Keycloak, Tinode, or Meilisearch code.

## Repository Pattern Example

```python
class PostgresUserRepository(UserRepository):
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def get_by_identity_subject(self, subject: str) -> User | None:
        row = await self._executor.fetchrow(
            "SELECT * FROM fn_get_user_by_identity_subject($1)",
            subject,
        )
        return map_user(row) if row else None

    async def create_from_identity(self, command: BootstrapUserCommand) -> User:
        row = await self._executor.fetchrow(
            "SELECT * FROM fn_create_user($1, $2, $3)",
            command.identity_subject,
            command.email,
            command.display_name,
        )
        return map_user(row)
```

Repository rules:

- Repositories return domain entities, not `asyncpg.Record`.
- Repositories hide SQL and stored functions.
- Repositories do not know about FastAPI.
- Transaction control belongs to use cases or Unit of Work.

## Infrastructure Adapter Examples

### Keycloak Token Verifier

```python
class KeycloakTokenVerifier(TokenVerifier):
    async def verify(self, access_token: str) -> AuthenticatedPrincipal:
        claims = await self._decode_jwt(access_token)
        return AuthenticatedPrincipal(
            subject=claims["sub"],
            email=claims.get("email"),
            display_name=claims.get("name"),
            roles=extract_roles(claims),
        )
```

### Tinode Chat Gateway

```python
class TinodeChatGateway(ChatGateway):
    async def ensure_chat_identity(self, command: EnsureChatIdentityCommand) -> ChatIdentity:
        payload = self._mapper.to_tinode_user_payload(command)
        response = await self._client.ensure_user(payload)
        return self._mapper.to_chat_identity(response)
```

### Meilisearch Adapter

```python
class MeilisearchTravelerSearchAdapter(TravelerSearchGateway):
    async def search(self, query: TravelerSearchQuery) -> TravelerSearchResult:
        response = await self._client.index(self._index).search(
            query.text,
            query.to_meilisearch_options(),
        )
        return self._mapper.to_search_result(response)
```

Adapter rules:

- Provider payloads stay in infrastructure.
- Provider exceptions are mapped before crossing the boundary.
- All network calls are async and timeout-bound.
- Adapters expose domain-facing methods.

## API Flow

```text
HTTP request
  -> core middleware
  -> api/v1 router
  -> api dependency resolves use case
  -> domain use case
  -> repository or gateway port
  -> infrastructure adapter
  -> database or provider
  -> domain entity/result
  -> api response schema
```

Routers must only:

- validate HTTP input
- call use cases
- map domain results to response schemas
- map expected exceptions to HTTP responses when needed

## Dependency Injection Strategy

Use FastAPI dependencies only in `api/v1/dependencies`.

```python
async def get_user_repository(
    executor: Annotated[PostgresExecutor, Depends(get_postgres_executor)],
) -> UserRepository:
    return PostgresUserRepository(executor)


async def get_bootstrap_user(
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> BootstrapUser:
    return BootstrapUser(users)
```

Rules:

- Domains use constructor injection.
- API dependencies assemble use cases.
- Infrastructure adapters are injected through ports.
- Tests override use cases or ports at the API boundary.

## Transaction Strategy

- One use case is the default transaction boundary.
- Use `UnitOfWork` when one use case writes through multiple repositories.
- Keep transactions short.
- Never hold a DB transaction while waiting on Tinode, Meilisearch, storage, SMS, email, or Redis.
- Use an outbox for reliable side effects when needed.

```python
class UnitOfWork(Protocol):
    users: UserRepository

    async def __aenter__(self) -> "UnitOfWork":
        ...

    async def __aexit__(self, exc_type, exc, tb) -> None:
        ...

    async def commit(self) -> None:
        ...
```

## Observability Integration Plan

Create `chatapp_backend/core/observability`.

Recommended files:

```text
observability/
├── health.py
├── metrics.py
└── tracing.py
```

Prometheus metrics:

- `http_requests_total`
- `http_request_duration_seconds`
- `http_errors_total`
- `db_pool_acquire_seconds`
- `db_pool_acquired_connections`
- `rate_limit_rejections_total`
- `external_provider_requests_total`
- `external_provider_duration_seconds`

Implementation options:

- Use `prometheus-client` for `/metrics`.
- Keep labels low-cardinality: method, route, status_code, provider.
- Do not label by user ID, package ID, token subject, or request ID.
- Keep health checks separate from metrics.
- Expose readiness at `/health/ready`.
- Expose liveness at `/health/live`.

## Testing Strategy

Target layout:

```text
chatapp_backend/tests/
├── unit/
│   ├── domains/
│   │   ├── users/
│   │   └── chat/
│   └── core/
├── api/
│   └── v1/
├── integration/
│   ├── database/
│   ├── keycloak/
│   ├── tinode/
│   └── meilisearch/
└── contracts/
    ├── keycloak/
    ├── tinode/
    └── meilisearch/
```

Rules:

- Domain unit tests use fake repositories and fake ports.
- API tests override dependencies.
- Integration tests may require Docker services.
- Contract tests verify provider request/response shapes.
- Middleware tests stay focused on cross-cutting behavior.
- Repository tests verify SQL mapping and transaction behavior.

## CI/CD Recommendations

Pipeline:

```text
lint
  -> ruff check .
  -> black --check .
  -> import boundary check

test
  -> pytest chatapp_backend/tests/unit
  -> pytest chatapp_backend/tests/api

integration
  -> docker compose up postgres keycloak tinode meilisearch
  -> run migrations
  -> pytest chatapp_backend/tests/integration

security
  -> dependency audit
  -> secret scan
  -> container image scan

build
  -> docker build
  -> push image

deploy
  -> run migrations
  -> deploy API
  -> verify /health/ready
```

Deployment rules:

- Run migrations as a separate job before application rollout.
- Keep migrations backward-compatible across one release.
- Fail deployment if readiness stays degraded.
- Never deploy local development secrets.
- Pin production image versions.

## Naming Conventions

Packages:

- `api.v1`
- `v1.users`
- `infrastructure.keycloak`
- `core.middleware`

Classes:

| Type | Pattern | Example |
| --- | --- | --- |
| Entity | noun | `User`, `Trip`, `ChatIdentity` |
| Command | verb + command | `BootstrapUserCommand` |
| Query | noun + query | `TravelerSearchQuery` |
| Use case | verb phrase | `BootstrapUser`, `CreateTrip` |
| Repository port | entity + repository | `UserRepository` |
| Adapter | provider + capability | `TinodeChatGateway` |
| Event | past-tense fact | `UserCreated` |
| Exception | domain + error | `UserNotFoundError` |

Files:

- Use case files: `bootstrap_user.py`, `create_trip.py`.
- Repository ports: `user_repository.py`.
- Infrastructure repositories: `users.py`.
- API schemas: `users.py`, `auth.py`, `common.py`.
- Provider adapters: `adapter.py`, `health.py`, `rest_auth.py`.

## Coding Standards

General:

- Prefer boring, explicit code over clever abstractions.
- Keep modules small and named by responsibility.
- Use type hints everywhere.
- Use dataclasses for domain entities and commands unless validation needs Pydantic.
- Use Pydantic for API schemas and provider DTOs.
- Do not return raw provider payloads from domain use cases.

Async:

- All I/O is async.
- Every external call must have a timeout.
- Avoid blocking calls in request handlers.
- Use `asyncio.to_thread()` only for unavoidable blocking libraries.
- Keep DB transactions short.

Errors:

- Domain raises domain exceptions.
- Infrastructure maps provider exceptions.
- API maps expected exceptions to HTTP responses.
- Middleware provides the fallback error response.

Logging:

- Use structured logs.
- Include request ID when available.
- Never log tokens, OTPs, secrets, or private package details.

Security:

- Keycloak verification belongs in infrastructure and API boundary dependencies.
- Middleware may attach principal context but must not contain business rules.
- Internal Tinode routes must require shared secret validation and network-level protection.

## Scalable FastAPI Best Practices

- Keep `api/v1` thin.
- Use dependency injection to assemble use cases.
- Use ASGI middleware only for cross-cutting concerns.
- Keep provider clients lifecycle-managed during startup/shutdown.
- Add Redis only for real cross-process needs: distributed rate limiting, websocket presence, cache, or background jobs.
- Use an outbox before introducing message brokers.
- Use route names, not raw paths with IDs, as metric labels.
- Keep Docker health checks separate from app readiness logic.
- Preserve one deployment until scale or team ownership justifies extraction.
