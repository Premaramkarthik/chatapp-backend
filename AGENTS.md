# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.13+ FastAPI backend. `main.py` is the application entrypoint. API routers, schemas, middleware, and dependencies live in `v1/`; business logic lives in `domains/`. External service clients and database repositories belong in `infrastructure/`, while shared configuration, logging, and observability live in `core/`.

Background jobs live in `workers/`. SQL migrations belong in `migrations/`; operational scripts in `scripts/`; tests in `tests/`. Use `deployment/` for service configuration and assets, and `docs/` for architecture and operational documentation.

## Build, Test, and Development Commands

Prefix shell commands with `rtk`, per `/home/zayn/.codex/RTK.md`. Use `rtk proxy` when a command needs unfiltered execution.

- `rtk proxy uv sync --extra dev`: install application and development dependencies.
- `rtk proxy docker compose up -d`: start the configured Compose stack; production PostgreSQL is external and must be provisioned first.
- `rtk proxy uv run python scripts/run_migrations.py`: apply pending SQL migrations.
- `rtk proxy uv run uvicorn main:app --reload`: start the development API.
- `rtk proxy uv run pytest -m "not integration and not e2e"`: run tests without external integration suites.
- `rtk proxy uv run black --check .` and `rtk proxy uv run ruff check .`: check formatting and lint rules.
- `rtk proxy docker build -t chatapp-backend .`: build the backend image.

## Coding Style & Naming Conventions

Use four-space indentation and a 100-character line limit. Black formats Python; Ruff checks imports and correctness. Use `snake_case` for modules and functions, `PascalCase` for classes, and type annotations consistent with nearby code. Keep route handling, business logic, and service adapters in their respective layers.

## Testing Guidelines

Use pytest and pytest-asyncio; async mode is automatic. Name files `test_*.py` and tests `test_*`. Add regression tests for changed behavior, including failure and permission cases. Integration tests require PostgreSQL and Keycloak; email end-to-end tests require SMTP configuration. No numeric coverage threshold is configured.

## Commit & Pull Request Guidelines

Follow Conventional Commits, such as `feat(search): add discovery filter` or `fix(auth): reject expired token`. Use lowercase scopes to satisfy the commit validator. PR descriptions should explain behavior changes, link related issues, list validation performed, and identify migration or configuration requirements.

## Security & Configuration

Use `.env.example` as the configuration template; never commit credentials or tokens. For this authentication overhaul, edit existing migrations and target a fresh local setup; do not add migration files or reset databases automatically. Existing applied histories are incompatible with renumbering. The runner verifies checksums; reserve `--repair-changed` for explicit local/development repair.
