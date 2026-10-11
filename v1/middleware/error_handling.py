"""HTTP error handling middleware."""

from __future__ import annotations

from fastapi import HTTPException, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from core.logging.logger import get_logger, log_exception, log_warning
from domains.auth.password_policy import PasswordPolicyError
from v1.middleware.state import REQUEST_ID_STATE_KEY, state_value
from v1.utils.base import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    DatabaseError,
    IntegrationError,
)

logger = get_logger(__name__)


class ErrorHandlingMiddleware:
    """Translate expected exceptions into consistent JSON responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except HTTPException as exc:
            request_id = state_value(scope, REQUEST_ID_STATE_KEY)
            await self._send_error(
                scope,
                receive,
                send,
                status_code=exc.status_code,
                code=(
                    exc.detail.get("code", "http_error")
                    if isinstance(exc.detail, dict)
                    else "http_error"
                ),
                message=(
                    exc.detail.get("message", "Request failed")
                    if isinstance(exc.detail, dict)
                    else str(exc.detail)
                ),
                request_id=request_id,
                headers=exc.headers,
            )
        except AppError as exc:
            request_id = state_value(scope, REQUEST_ID_STATE_KEY)
            status_code = _status_for_app_error(exc)
            log_warning(
                logger,
                "Application error returned to client",
                code=exc.code,
                status_code=status_code,
                request_id=request_id,
                method=scope.get("method"),
                path=scope.get("path"),
                detail=exc.message,
            )
            await self._send_error(
                scope,
                receive,
                send,
                status_code=status_code,
                code=exc.code,
                message=exc.message,
                request_id=request_id,
            )
        except Exception as exc:
            request_id = state_value(scope, REQUEST_ID_STATE_KEY)
            log_exception(
                logger,
                "Unhandled error while processing HTTP request",
                request_id=request_id,
                error_type=type(exc).__name__,
                detail=exc,
            )
            await self._send_error(
                scope,
                receive,
                send,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="internal_server_error",
                message="Internal server error",
                request_id=request_id,
            )

    @staticmethod
    async def _send_error(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
        request_id: str | None,
        headers: dict[str, str] | None = None,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request_id,
                }
            },
            headers=headers,
        )
        await response(scope, receive, send)


def _status_for_app_error(exc: AppError) -> int:
    if isinstance(exc, PasswordPolicyError):
        return status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, AuthenticationError):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(exc, AuthorizationError):
        return status.HTTP_403_FORBIDDEN
    if isinstance(exc, (DatabaseError, IntegrationError)):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    return status.HTTP_400_BAD_REQUEST
