"""One error type for everything a player can be told: an i18n `reason_key` + status.

HTTP routes, WebSocket handlers and worker replies all raise/return `GameError`; one
FastAPI handler turns it into `{reason_key, detail}` (docs/protocol.md).
"""

from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.combat.ground.resolver import IllegalAction


class GameError(Exception):
    def __init__(
        self,
        reason_key: str,
        status: int = 400,
        *,
        detail: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(reason_key)
        self.reason_key = reason_key
        self.status = status
        self.detail = detail
        self.headers = dict(headers or {})

    def body(self) -> dict[str, str]:
        body = {"reason_key": self.reason_key}
        if self.detail:
            body["detail"] = self.detail
        return body


def from_illegal_action(exc: IllegalAction) -> GameError:
    return GameError(exc.reason, 400)


async def _handle_game_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GameError)
    return JSONResponse(exc.body(), status_code=exc.status, headers=exc.headers)


async def _handle_illegal_action(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, IllegalAction)
    return await _handle_game_error(request, from_illegal_action(exc))


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields = ", ".join(".".join(map(str, e["loc"])) for e in exc.errors())
    return await _handle_game_error(
        request, GameError("request.invalid", 400, detail=fields)
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(GameError, _handle_game_error)
    app.add_exception_handler(IllegalAction, _handle_illegal_action)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
