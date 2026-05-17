"""Request state helpers shared by middleware and dependencies."""

from __future__ import annotations

from typing import Any

from starlette.types import Scope

REQUEST_ID_STATE_KEY = "request_id"
START_TIME_STATE_KEY = "start_time"
PRINCIPAL_STATE_KEY = "principal"
DB_CONNECTION_STATE_KEY = "db"
RATE_LIMIT_STATE_KEY = "rate_limit"


def ensure_state(scope: Scope) -> dict[str, Any]:
    """Return the mutable ASGI state mapping for a request scope."""
    state = scope.setdefault("state", {})
    if not isinstance(state, dict):
        state = {}
        scope["state"] = state
    return state


def state_value(scope: Scope, key: str, default: Any = None) -> Any:
    """Read one value from request state."""
    state = ensure_state(scope)
    return state.get(key, default)
