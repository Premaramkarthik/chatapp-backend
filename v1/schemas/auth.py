"""Authentication models."""

from pydantic import BaseModel


class TinodeAuthRequest(BaseModel):
    """Subset of Tinode REST authenticator payload used by chatapp."""

    endpoint: str | None = None
    secret: str | None = None
    addr: str | None = None
    rec: dict | None = None


class TinodeAuthResponse(BaseModel):
    """Flexible Tinode REST authenticator response."""

    err: str | None = None
    rec: dict | None = None
    newacc: dict | None = None
    strarr: list[str] | None = None
    boolval: bool | None = None
