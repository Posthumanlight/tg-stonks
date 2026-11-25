"""Auth request/response bodies (docs/protocol.md "HTTP endpoints")."""

from pydantic import Field

from app.protocol.base import ProtocolModel
from app.protocol.errors import SetupErrorRef


class RegisterRequest(ProtocolModel):
    username: str = Field(max_length=64)  # the real rules live in app/auth/rules.py
    password: str = Field(max_length=256)


class LoginRequest(ProtocolModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class UserView(ProtocolModel):
    user_id: int
    username: str
    role: str


class TokenResponse(ProtocolModel):
    access_token: str
    expires_in: int  # seconds
    user: UserView


class ErrorBody(ProtocolModel):
    """Every HTTP error: an i18n reason key and an optional developer detail."""

    reason_key: str
    # A developer message, or for `setup.*` errors the offending side and unit.
    detail: str | SetupErrorRef | None = None
