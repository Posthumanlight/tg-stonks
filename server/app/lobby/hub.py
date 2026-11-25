"""Room subscriptions and pushes over the WebSocket (docs/lobby-rooms.md).

A member's open sockets subscribed to their room are their presence: when the last
one goes, the service starts the member's grace period. Each push is rendered per
viewer (the opponent's deployment stays hidden).
"""

from collections.abc import Callable
from typing import Any, Protocol

from app.lobby.room import Room


class RoomSubscriber(Protocol):
    """What the hub needs from a connection (implemented by the WS layer)."""

    @property
    def user_id(self) -> int: ...

    def send(self, message: dict[str, Any]) -> None: ...


Render = Callable[[Room, int], dict[str, Any]]  # (room, viewer) -> RoomView JSON


class RoomHub:
    def __init__(self, render: Render) -> None:
        self._render = render
        self._subscribers: dict[str, set[RoomSubscriber]] = {}

    def add(self, room_id: str, subscriber: RoomSubscriber) -> None:
        self._subscribers.setdefault(room_id, set()).add(subscriber)

    def remove(self, room_id: str, subscriber: RoomSubscriber) -> bool:
        """Unsubscribe. True when that user has no other socket left in the room."""
        subscribers = self._subscribers.get(room_id)
        if subscribers is None or subscriber not in subscribers:
            return False
        subscribers.discard(subscriber)
        if not subscribers:
            del self._subscribers[room_id]
        return not self.present(room_id, subscriber.user_id)

    def rooms_of(self, subscriber: RoomSubscriber) -> list[str]:
        return [rid for rid, subs in self._subscribers.items() if subscriber in subs]

    def present(self, room_id: str, user_id: int) -> bool:
        return any(s.user_id == user_id for s in self._subscribers.get(room_id, ()))

    def publish(self, room: Room) -> None:
        """`room.state` to every subscribed member, each with their own view."""
        for subscriber in list(self._subscribers.get(room.room_id, ())):
            if room.is_member(subscriber.user_id):
                subscriber.send(
                    {
                        "type": "room.state",
                        "payload": self._render(room, subscriber.user_id),
                    }
                )

    def started(self, room_id: str, combat_id: str) -> None:
        """The battle began: tell everyone, then forget the room's subscriptions."""
        self._final(
            room_id,
            {
                "type": "room.started",
                "payload": {"room_id": room_id, "combat_id": combat_id},
            },
        )

    def closed(
        self, room_id: str, reason: str, *, only: frozenset[int] | None = None
    ) -> None:
        """`room.closed {reason}` to the room's sockets (or just `only` users', e.g. a
        kicked guest's), and drop those subscriptions."""
        self._final(
            room_id,
            {"type": "room.closed", "payload": {"room_id": room_id, "reason": reason}},
            only=only,
        )

    def _final(
        self,
        room_id: str,
        message: dict[str, Any],
        *,
        only: frozenset[int] | None = None,
    ) -> None:
        subscribers = self._subscribers.get(room_id, set())
        for subscriber in list(subscribers):
            if only is None or subscriber.user_id in only:
                subscriber.send(message)
                subscribers.discard(subscriber)
        if not subscribers:
            self._subscribers.pop(room_id, None)
