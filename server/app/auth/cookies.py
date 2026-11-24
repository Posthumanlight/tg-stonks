"""The refresh cookie: one place owns its name and flags (docs/architecture.md)."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Request, Response

from app.shared.errors import GameError


@dataclass(frozen=True, slots=True)
class CookiePolicy:
    secure: bool
    max_age: int

    @property
    def name(self) -> str:
        # The __Host- prefix requires Secure; plain-HTTP local dev uses a bare name.
        return "__Host-refresh" if self.secure else "refresh"

    def set(self, response: Response, raw: str) -> None:
        response.set_cookie(
            self.name,
            raw,
            max_age=self.max_age,
            path="/",
            secure=self.secure,
            httponly=True,
            samesite="strict",
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(
            self.name, path="/", secure=self.secure, httponly=True, samesite="strict"
        )

    def read(self, request: Request) -> str | None:
        return request.cookies.get(self.name)


def check_same_origin(request: Request) -> None:
    """Defence in depth for cookie-authenticated endpoints (CSRF)."""
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if not origin or not host or urlsplit(origin).netloc != host:
        raise GameError("auth.bad_origin", 403)
