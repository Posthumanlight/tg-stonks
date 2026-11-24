"""Auth routes. Thin: validation and flows live in `app.auth.service`."""

from fastapi import APIRouter, Depends, Request, Response

from app.auth.cookies import check_same_origin
from app.auth.dependencies import client_ip, current_user, enforce_limit, get_auth
from app.auth.rules import normalize_username
from app.auth.service import Session
from app.auth.tokens import Principal
from app.persistence.auth_repo import UserRecord
from app.protocol.auth import LoginRequest, RegisterRequest, TokenResponse, UserView
from app.shared.errors import GameError

router = APIRouter(prefix="/auth")


def user_view(user: UserRecord) -> UserView:
    return UserView(user_id=user.user_id, username=user.username, role=user.role)


def _session_response(
    request: Request, response: Response, session: Session
) -> TokenResponse:
    get_auth(request).cookie.set(response, session.refresh.raw)
    return TokenResponse(
        access_token=session.access.token,
        expires_in=session.access.expires_in,
        user=user_view(session.user),
    )


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, request: Request) -> UserView:
    auth = get_auth(request)
    enforce_limit(auth.limits.register_ip, client_ip(request))
    return user_view(await auth.service.register(body.username, body.password))


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response
) -> TokenResponse:
    auth = get_auth(request)
    enforce_limit(auth.limits.login_ip, client_ip(request))
    enforce_limit(auth.limits.login_user, normalize_username(body.username))
    session = await auth.service.login(body.username, body.password)
    return _session_response(request, response, session)


@router.post("/refresh")
async def refresh(request: Request, response: Response) -> TokenResponse:
    auth = get_auth(request)
    check_same_origin(request)
    enforce_limit(auth.limits.refresh_ip, client_ip(request))
    raw = auth.cookie.read(request)
    if not raw:
        raise GameError("auth.invalid_refresh", 401)
    try:
        session = await auth.service.refresh(raw)
    except GameError as exc:
        if exc.reason_key == "auth.invalid_refresh":
            auth.cookie.clear(response)
            exc.headers.update(response.headers)  # carry the clearing Set-Cookie
        raise
    return _session_response(request, response, session)


@router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    auth = get_auth(request)
    check_same_origin(request)
    await auth.service.logout(auth.cookie.read(request))
    response = Response(status_code=204)
    auth.cookie.clear(response)
    return response


@router.post("/logout-all", status_code=204)
async def logout_all(
    request: Request, principal: Principal = Depends(current_user)
) -> Response:
    auth = get_auth(request)
    await auth.service.logout_all(principal.user_id)
    response = Response(status_code=204)
    auth.cookie.clear(response)
    return response


@router.get("/me")
async def me(
    request: Request, principal: Principal = Depends(current_user)
) -> UserView:
    user = await get_auth(request).service.users.get(principal.user_id)
    if user is None:
        raise GameError("auth.invalid_token", 401)
    return user_view(user)
