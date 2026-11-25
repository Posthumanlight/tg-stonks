"""Lobby room routes (docs/protocol.md "Lobby rooms"). Room changes are pushed to the
members over the WebSocket (`room.subscribe`); these routes make the changes."""

from fastapi import APIRouter, Depends, Query, Request, Response

from app.auth.dependencies import current_user
from app.auth.tokens import Principal
from app.lobby.room import Room
from app.lobby.service import RoomService
from app.protocol.builder import SideSetup
from app.protocol.rooms import (
    ROOM_LIST_MAX,
    CreateRoomRequest,
    JoinByCodeRequest,
    MyRoom,
    RoomJoined,
    RoomList,
    RoomReady,
    room_card,
)

router = APIRouter(prefix="/rooms")


def get_rooms(request: Request) -> RoomService:
    return request.app.state.rooms


def _joined(room: Room) -> RoomJoined:
    return RoomJoined(room_id=room.room_id, code=room.code)


@router.post("", status_code=201)
async def create_room(
    body: CreateRoomRequest,
    request: Request,
    principal: Principal = Depends(current_user),
) -> RoomJoined:
    return _joined(await get_rooms(request).create(principal.user_id, body))


@router.get("", dependencies=[Depends(current_user)])
async def search_rooms(
    request: Request,
    q: str = Query("", max_length=40),
    points: int | None = Query(None, ge=0),
) -> RoomList:
    rooms = get_rooms(request).search(q, points, ROOM_LIST_MAX)
    return RoomList(rooms=[room_card(r) for r in rooms])


@router.get("/mine")
async def my_room(
    request: Request, principal: Principal = Depends(current_user)
) -> MyRoom:
    """The room the user is in, if any (the lobby's "Back to room")."""
    room = get_rooms(request).mine(principal.user_id)
    return MyRoom(room=_joined(room) if room is not None else None)


@router.post("/join")
async def join_by_code(
    body: JoinByCodeRequest,
    request: Request,
    principal: Principal = Depends(current_user),
) -> RoomJoined:
    return _joined(await get_rooms(request).join(principal.user_id, code=body.code))


@router.post("/{room_id}/join")
async def join_room(
    room_id: str, request: Request, principal: Principal = Depends(current_user)
) -> RoomJoined:
    return _joined(await get_rooms(request).join(principal.user_id, room_id=room_id))


@router.post("/{room_id}/ready")
async def ready(
    room_id: str,
    body: SideSetup,
    request: Request,
    principal: Principal = Depends(current_user),
) -> RoomReady:
    combat_id = await get_rooms(request).ready(principal.user_id, room_id, body)
    return RoomReady(combat_id=combat_id)


@router.post("/{room_id}/unready", status_code=204)
async def unready(
    room_id: str, request: Request, principal: Principal = Depends(current_user)
) -> Response:
    get_rooms(request).unready(principal.user_id, room_id)
    return Response(status_code=204)


@router.post("/{room_id}/leave", status_code=204)
async def leave(
    room_id: str, request: Request, principal: Principal = Depends(current_user)
) -> Response:
    get_rooms(request).leave(principal.user_id, room_id)
    return Response(status_code=204)


@router.post("/{room_id}/kick", status_code=204)
async def kick(
    room_id: str, request: Request, principal: Principal = Depends(current_user)
) -> Response:
    get_rooms(request).kick(principal.user_id, room_id)
    return Response(status_code=204)
