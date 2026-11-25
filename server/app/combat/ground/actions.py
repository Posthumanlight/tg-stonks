"""Player intents. All but `Concede` are for the active unit; the engine validates
every one of them."""

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


@dataclass(frozen=True, slots=True)
class Concede:
    """A side gives up (an online player's surrender), at any time: the fight ends and
    the other sides win. Takes no turn and rolls no dice."""

    side: int


Action = Move | Attack | UseAbility | Wait | Skip | Concede
