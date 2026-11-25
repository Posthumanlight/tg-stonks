"""Where rooms live: an interface plus the in-memory store (docs/lobby-rooms.md).

The gateway is a single process, so memory is the source of truth for rooms; started
battles are persisted combats. Scaling to several gateways swaps `MemoryRoomStore` for
a shared one (e.g. Redis) behind the same `RoomStore` interface.
"""

import secrets
from typing import Protocol

from app.lobby.room import OPEN, Room

# Crockford base32: no I, L, O, U, so codes are easy to read aloud and type.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 6
_CONFUSABLE = str.maketrans({"O": "0", "I": "1", "L": "1"})


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(text: str) -> str:
    """What a player typed, as a code: case, spaces, dashes and look-alikes forgiven."""
    cleaned = text.strip().upper().replace("-", "").replace(" ", "")
    return cleaned.translate(_CONFUSABLE)


class RoomStore(Protocol):
    def add(self, room: Room) -> None: ...

    def get(self, room_id: str) -> Room | None: ...

    def by_code(self, code: str) -> Room | None: ...

    def of_user(self, user_id: int) -> Room | None:
        """The room the user is a member of (at most one)."""
        ...

    def bind(self, user_id: int, room_id: str) -> None:
        """Record membership (after a create or join)."""
        ...

    def unbind(self, user_id: int) -> None: ...

    def remove(self, room_id: str) -> Room | None:
        """Drop the room, its code and its members' bindings."""
        ...

    def code_taken(self, code: str) -> bool: ...

    def search(self, query: str, points_limit: int | None, limit: int) -> list[Room]:
        """Open public rooms, newest first; `query` matches the name (any case),
        `points_limit` the room's exactly (None = any)."""
        ...

    def all(self) -> list[Room]: ...


class MemoryRoomStore:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._codes: dict[str, str] = {}
        self._users: dict[int, str] = {}

    def add(self, room: Room) -> None:
        self._rooms[room.room_id] = room
        self._codes[room.code] = room.room_id

    def get(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    def by_code(self, code: str) -> Room | None:
        room_id = self._codes.get(code)
        return self._rooms.get(room_id) if room_id is not None else None

    def of_user(self, user_id: int) -> Room | None:
        room_id = self._users.get(user_id)
        return self._rooms.get(room_id) if room_id is not None else None

    def bind(self, user_id: int, room_id: str) -> None:
        self._users[user_id] = room_id

    def unbind(self, user_id: int) -> None:
        self._users.pop(user_id, None)

    def remove(self, room_id: str) -> Room | None:
        room = self._rooms.pop(room_id, None)
        if room is not None:
            self._codes.pop(room.code, None)
            for member in room.members:
                if self._users.get(member.user_id) == room_id:
                    del self._users[member.user_id]
        return room

    def code_taken(self, code: str) -> bool:
        return code in self._codes

    def search(self, query: str, points_limit: int | None, limit: int) -> list[Room]:
        needle = query.strip().casefold()
        found = [
            room
            for room in self._rooms.values()
            if room.status == OPEN
            and not room.settings.private
            and needle in room.settings.name.casefold()
            and (points_limit is None or room.settings.points_limit == points_limit)
        ]
        found.sort(key=lambda r: (r.created_at, r.room_id), reverse=True)
        return found[:limit]

    def all(self) -> list[Room]:
        return list(self._rooms.values())
