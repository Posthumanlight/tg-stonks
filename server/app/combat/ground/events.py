"""The public event log: what the client animates and what replays are checked against.

Hook events (raised for abilities) are defined in `hooks.py`; these are log entries.
"""

import dataclasses
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, ClassVar

from app.combat.ground.board import Square


@dataclass(frozen=True, slots=True)
class Event:
    kind: ClassVar[str] = "event"


@dataclass(frozen=True, slots=True)
class CombatStarted(Event):
    kind: ClassVar[str] = "combat_started"
    side_order: tuple[int, ...]
    units: tuple[
        tuple[int, str, int, Square, int], ...
    ]  # uid, type, side, origin, models


@dataclass(frozen=True, slots=True)
class RoundStarted(Event):
    kind: ClassVar[str] = "round_started"
    round: int
    order: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RoundEnded(Event):
    kind: ClassVar[str] = "round_ended"
    round: int


@dataclass(frozen=True, slots=True)
class ActivationStarted(Event):
    kind: ClassVar[str] = "activation_started"
    unit: int
    movement: int
    action_points: int


@dataclass(frozen=True, slots=True)
class ActivationEnded(Event):
    kind: ClassVar[str] = "activation_ended"
    unit: int


@dataclass(frozen=True, slots=True)
class UnitWaited(Event):
    kind: ClassVar[str] = "unit_waited"
    unit: int


@dataclass(frozen=True, slots=True)
class UnitMoved(Event):
    kind: ClassVar[str] = "unit_moved"
    unit: int
    from_square: Square
    to_square: Square
    cost: int


@dataclass(frozen=True, slots=True)
class UnitRepositioned(Event):
    """Moved by an effect (push, teleport) or a move falling back to a free square."""

    kind: ClassVar[str] = "unit_repositioned"
    unit: int
    from_square: Square
    to_square: Square
    reason: str


@dataclass(frozen=True, slots=True)
class Rolled(Event):
    """Every random draw. kind: dice | chance | round | side_order."""

    kind: ClassVar[str] = "rolled"
    source: str
    roll: str
    spec: str
    values: tuple[int, ...]
    result: int


@dataclass(frozen=True, slots=True)
class AttackDeclared(Event):
    kind: ClassVar[str] = "attack_declared"
    attacker: int
    target: int
    weapon: str
    opportunity: bool
    ap_cost: int


@dataclass(frozen=True, slots=True)
class HitResolved(Event):
    kind: ClassVar[str] = "hit_resolved"
    source: int
    target: int
    index: int
    damage: int  # after modifiers and rounding
    applied: int  # damage actually removed (no spill)
    cover: bool
    killed_role: str | None


@dataclass(frozen=True, slots=True)
class HitPrevented(Event):
    kind: ClassVar[str] = "hit_prevented"
    source: int
    target: int
    index: int


@dataclass(frozen=True, slots=True)
class ModelKilled(Event):
    kind: ClassVar[str] = "model_killed"
    unit: int
    role: str
    source: int | None


@dataclass(frozen=True, slots=True)
class UnitDestroyed(Event):
    kind: ClassVar[str] = "unit_destroyed"
    unit: int
    source: int | None


@dataclass(frozen=True, slots=True)
class AttackResolved(Event):
    kind: ClassVar[str] = "attack_resolved"
    attacker: int
    target: int
    weapon: str
    hits: int
    total_damage: int
    kills: int


@dataclass(frozen=True, slots=True)
class AbilityUsed(Event):
    kind: ClassVar[str] = "ability_used"
    unit: int
    ability: str
    target_unit: int | None
    target_square: Square | None


@dataclass(frozen=True, slots=True)
class StatusApplied(Event):
    kind: ClassVar[str] = "status_applied"
    unit: int
    status: str
    rounds: int
    stacks: int


@dataclass(frozen=True, slots=True)
class StatusExpired(Event):
    kind: ClassVar[str] = "status_expired"
    unit: int
    status: str


@dataclass(frozen=True, slots=True)
class OverlayPlaced(Event):
    kind: ClassVar[str] = "overlay_placed"
    square: Square
    overlay: str
    rounds: int


@dataclass(frozen=True, slots=True)
class OverlayExpired(Event):
    kind: ClassVar[str] = "overlay_expired"
    square: Square
    overlay: str


@dataclass(frozen=True, slots=True)
class Healed(Event):
    kind: ClassVar[str] = "healed"
    unit: int
    amount: int


@dataclass(frozen=True, slots=True)
class ModelsRevived(Event):
    kind: ClassVar[str] = "models_revived"
    unit: int
    count: int


@dataclass(frozen=True, slots=True)
class UnitSpawned(Event):
    kind: ClassVar[str] = "unit_spawned"
    unit: int
    unit_type: str
    side: int
    origin: Square
    models: int


@dataclass(frozen=True, slots=True)
class LogMessage(Event):
    kind: ClassVar[str] = "log_message"
    key: str
    params: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class HookError(Event):
    """A hooked ability function raised; its trigger run was rolled back."""

    kind: ClassVar[str] = "hook_error"
    ability: str
    event: str
    error: str


@dataclass(frozen=True, slots=True)
class CombatEnded(Event):
    kind: ClassVar[str] = "combat_ended"
    winners: tuple[int, ...]
    draw: bool
    reason: str


def _plain(value: Any) -> Any:
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def event_to_dict(event: Event) -> dict[str, Any]:
    data = {f.name: _plain(getattr(event, f.name)) for f in dataclasses.fields(event)}
    return {"type": event.kind, **data}


def log_hash(events: Iterable[Event]) -> str:
    """Canonical hash of an event log (golden-fight tests, replay checks)."""
    data = [event_to_dict(e) for e in events]
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()
