"""Health and system routes."""

from fastapi import APIRouter, Response, status

from core.config.settings import settings
from infrastructure.database.connection import call_json_function
from infrastructure.keycloak.adapter import keycloak_verifier
from infrastructure.matrix.health import matrix_admin_health, matrix_health
from infrastructure.typesense.health import health as typesense_health

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(response: Response) -> dict:
    """Readiness check across required Phase 1 dependencies."""
    checks: dict[str, dict] = {
        "database": await _check_database(),
        "keycloak": (await keycloak_verifier.health()).__dict__,
    }
    if settings.typesense.enabled:
        checks["typesense"] = (await typesense_health()).__dict__
    if settings.matrix.enabled:
        checks["matrix"] = (await matrix_health()).__dict__
        checks["matrix_admin"] = (await matrix_admin_health()).__dict__
    ok = all(check["ok"] for check in checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "degraded", "checks": checks}


@router.get("/v1/system/version")
async def version() -> dict[str, str]:
    """Return app version metadata."""
    return {
        "name": settings.app.name,
        "version": settings.app.version,
        "environment": settings.app.environment,
    }


async def _check_database() -> dict[str, str | bool]:
    try:
        result = await call_json_function("fn_health", 1, {})
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    return {"ok": bool(result and result.get("ok")), "detail": "ok"}
