"""HTTP error handling middleware."""

from __future__ import annotations

from fastapi import HTTPException, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from v1.middleware.state import REQUEST_ID_STATE_KEY, state_value
from v1.utils.exception import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    DatabaseError,
    IntegrationError,
)
from v1.utils.logger import get_logger

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
                code="http_error",
                message=str(exc.detail),
                request_id=request_id,
                headers=exc.headers,
            )
        except AppError as exc:
            request_id = state_value(scope, REQUEST_ID_STATE_KEY)
            status_code = _status_for_app_error(exc)
            logger.warning(
                "app_error code={} status_code={} request_id={} detail={}",
                exc.code,
                status_code,
                request_id,
                exc.message,
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
            logger.exception(
                "unhandled_request_error request_id={} error_type={} detail={}",
                request_id,
                type(exc).__name__,
                exc,
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
    if isinstance(exc, AuthenticationError):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(exc, AuthorizationError):
        return status.HTTP_403_FORBIDDEN
    if isinstance(exc, (DatabaseError, IntegrationError)):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    return status.HTTP_400_BAD_REQUEST
