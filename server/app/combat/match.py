"""Who plays a combat and how (docs/architecture.md "Combat modes"): its mode, the seats
(side -> user) and the turn timer. Shell-level, like seeds: the pure engine never sees
any of it, so it lives beside the engine, not in it."""

from collections.abc import Iterable
from dataclasses import dataclass

HOTSEAT = "hotseat"
PVP = "pvp"


@dataclass(frozen=True, slots=True)
class Seat:
    side: int
    user_id: int
    name: str = ""  # the player's name at start (labels); "" for hotseat


@dataclass(frozen=True, slots=True)
class Match:
    owner_user_id: int  # who created it: the hotseat player, or the room's host
    mode: str
    seats: tuple[Seat, ...]
    timer_s: int | None = None  # seconds per activation; None = untimed

    @property
    def user_ids(self) -> frozenset[int]:
        return frozenset(s.user_id for s in self.seats)

    def seat_map(self) -> dict[int, int]:
        return {s.side: s.user_id for s in self.seats}

    @classmethod
    def hotseat(cls, owner_user_id: int, sides: Iterable[int]) -> "Match":
        """One user holds every side; no timer."""
        return cls(
            owner_user_id,
            HOTSEAT,
            tuple(Seat(side, owner_user_id) for side in sorted(set(sides))),
        )
