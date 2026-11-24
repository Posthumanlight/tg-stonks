"""Player intents for the active unit. The engine validates every one of them."""

from dataclasses import dataclass

from app.combat.ground.board import Square


@dataclass(frozen=True, slots=True)
class Move:
    path: tuple[Square, ...]  # successive origins, excluding the current one


@dataclass(frozen=True, slots=True)
class Attack:
    weapon: str
    target: int


@dataclass(frozen=True, slots=True)
class UseAbility:
    ability: str
    target_unit: int | None = None
    target_square: Square | None = None


@dataclass(frozen=True, slots=True)
class Wait:
    pass


@dataclass(frozen=True, slots=True)
class Skip:
    pass


Action = Move | Attack | UseAbility | Wait | Skip
