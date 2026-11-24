"""Combat state: frozen dataclasses, replaced (never mutated) as the fight progresses."""

from dataclasses import dataclass, replace

from app.combat.ground.board import Board, Square, footprint

UnitId = int  # index into CombatState.units (deployment order; spawned units append)


@dataclass(frozen=True, slots=True)
class GroupState:
    role: str
    alive: int
    initial: int
    hp: int  # per model
    weapons: tuple[str, ...]
    casualty_priority: int


@dataclass(frozen=True, slots=True)
class StatusState:
    status: str
    rounds_left: int
    stacks: int = 1


@dataclass(frozen=True, slots=True)
class UnitState:
    uid: UnitId
    unit_type: str
    side: int
    origin: Square  # top-left square of the footprint
    size: int  # footprint side: 1 or 2
    groups: tuple[GroupState, ...]
    wounded: tuple[int, int] | None = None  # (group index, hp left) — at most one model
    statuses: tuple[StatusState, ...] = ()
    reactions: int = 0
    waited: bool = False  # this round
    cooldowns: tuple[tuple[str, int], ...] = ()  # (ability, rounds left), only > 0
    uses: tuple[tuple[str, int], ...] = ()  # (ability, times used)

    @property
    def models(self) -> int:
        return sum(g.alive for g in self.groups)

    @property
    def initial_models(self) -> int:
        return sum(g.initial for g in self.groups)

    @property
    def alive(self) -> bool:
        return self.models > 0

    @property
    def squares(self) -> tuple[Square, ...]:
        return footprint(self.origin, self.size)

    def weapons(self) -> tuple[str, ...]:
        """Weapons carried by living models, in loadout order, without duplicates."""
        seen: dict[str, None] = {}
        for group in self.groups:
            if group.alive:
                for weapon in group.weapons:
                    seen.setdefault(weapon, None)
        return tuple(seen)

    def carriers(self, weapon: str) -> int:
        return sum(g.alive for g in self.groups if weapon in g.weapons)

    def cooldown(self, ability: str) -> int:
        return dict(self.cooldowns).get(ability, 0)

    def used(self, ability: str) -> int:
        return dict(self.uses).get(ability, 0)

    def has_status(self, status: str) -> bool:
        return any(s.status == status for s in self.statuses)


@dataclass(frozen=True, slots=True)
class OverlayState:
    square: Square
    overlay: str
    rounds_left: int


@dataclass(frozen=True, slots=True)
class Activation:
    uid: UnitId
    movement_left: int
    ap_left: int
    weapons_used: tuple[str, ...] = ()
    moved: bool = False
    attacked: bool = False
    movement_locked: bool = False  # set by attacking, unless an ability keeps movement
    acted: bool = False  # any action taken (Wait is only legal before this)


@dataclass(frozen=True, slots=True)
class Outcome:
    winners: tuple[int, ...]  # winning side(s); empty or several when drawn
    draw: bool
    reason: str  # "annihilation" | "round_limit"


@dataclass(frozen=True, slots=True)
class CombatState:
    board: Board
    side_order: tuple[int, ...]  # seeded at start; tie-break order rotates each round
    round: int = 0
    units: tuple[UnitState, ...] = ()
    overlays: tuple[OverlayState, ...] = ()
    round_order: tuple[UnitId, ...] = ()  # full main-queue order of the current round
    queue: tuple[UnitId, ...] = ()  # main queue still to act
    wait_queue: tuple[UnitId, ...] = ()
    active: Activation | None = None
    outcome: Outcome | None = None

    def unit(self, uid: UnitId) -> UnitState:
        return self.units[uid]

    def with_unit(self, unit: UnitState) -> "CombatState":
        units = list(self.units)
        units[unit.uid] = unit
        return replace(self, units=tuple(units))

    def living(self) -> tuple[UnitState, ...]:
        return tuple(u for u in self.units if u.alive)

    def sides_alive(self) -> tuple[int, ...]:
        return tuple(sorted({u.side for u in self.units if u.alive}))

    def tie_order(self) -> tuple[int, ...]:
        """Side tie-break order for the current round: the seeded order, rotated."""
        if not self.side_order:
            return ()
        shift = (max(self.round, 1) - 1) % len(self.side_order)
        return self.side_order[shift:] + self.side_order[:shift]
