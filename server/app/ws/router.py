"""WebSocket message handlers, registered by type on the shared Dispatcher.

Adding a message type = adding a handler here; the gateway loop never changes.
Handlers raise GameError to answer `error {id, reason_key}`; success answers `ack {id}`.
"""

from dataclasses import dataclass

from app.auth.tokens import TokenService
from app.lobby.service import RoomService
from app.protocol import ws
from app.services.combat_router import CombatRouter
from app.shared.dispatch import Dispatcher
from app.shared.errors import GameError
from app.ws.connection import Connection


@dataclass(frozen=True, slots=True)
class WsContext:
    connection: Connection
    tokens: TokenService
    combats: CombatRouter
    rooms: RoomService


dispatcher: Dispatcher[WsContext] = Dispatcher()


@dispatcher.on("ping")
async def ping(ctx: WsContext, msg: ws.PingMessage) -> None:
    ctx.connection.send(ws.PongMessage(type="pong", id=msg.id).model_dump(mode="json"))


@dispatcher.on("auth.refresh")
async def auth_refresh(ctx: WsContext, msg: ws.AuthRefreshMessage) -> None:
    principal = ctx.tokens.verify(msg.payload.access_token)
    if principal.user_id != ctx.connection.user_id:
        raise GameError("auth.forbidden", 403)
    ctx.connection.principal = principal


@dispatcher.on("combat.subscribe")
async def subscribe(ctx: WsContext, msg: ws.SubscribeMessage) -> None:
    reply = await ctx.combats.subscribe(
        ctx.connection,
        ctx.connection.user_id,
        msg.payload.combat_id,
        msg.payload.last_seq,
    )
    if reply["kind"] == "snapshot":
        ctx.connection.send({"type": "combat.snapshot", "payload": reply["snapshot"]})
    else:
        ctx.connection.send({"type": "combat.events", "payload": reply["update"]})


@dispatcher.on("combat.unsubscribe")
async def unsubscribe(ctx: WsContext, msg: ws.UnsubscribeMessage) -> None:
    ctx.combats.unsubscribe(ctx.connection, msg.payload.combat_id)


@dispatcher.on("combat.action")
async def action(ctx: WsContext, msg: ws.ActionMessage) -> None:
    intent = msg.payload.intent.model_dump(mode="json")
    await ctx.combats.intent(ctx.connection.user_id, msg.payload.combat_id, intent)


@dispatcher.on("room.subscribe")
async def room_subscribe(ctx: WsContext, msg: ws.RoomSubscribeMessage) -> None:
    ctx.rooms.subscribe(ctx.connection, msg.payload.room_id)


@dispatcher.on("room.unsubscribe")
async def room_unsubscribe(ctx: WsContext, msg: ws.RoomUnsubscribeMessage) -> None:
    ctx.rooms.unsubscribe(ctx.connection, msg.payload.room_id)
