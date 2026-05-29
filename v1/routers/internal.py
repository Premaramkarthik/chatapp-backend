"""Internal service-to-service routes."""

from fastapi import APIRouter, Header, HTTPException, Query, status

from infrastructure.tinode.rest_auth import (
    handle_tinode_request,
    verify_shared_secret,
)
from v1.schemas.auth import TinodeAuthRequest, TinodeAuthResponse
from v1.utils.base import TinodeAuthError

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/tinode/auth", response_model=TinodeAuthResponse)
async def tinode_auth(
    payload: TinodeAuthRequest,
    x_paripath_tinode_secret: str | None = Header(default=None),
    shared_secret: str | None = Query(default=None),
) -> dict:
    """Tinode REST authenticator callback."""
    try:
        verify_shared_secret(x_paripath_tinode_secret, shared_secret)
    except TinodeAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    try:
        return await handle_tinode_request(payload.model_dump(exclude_none=True))
    except TinodeAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
