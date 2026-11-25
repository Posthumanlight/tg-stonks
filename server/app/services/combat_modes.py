"""What differs between combat modes at the gateway (docs/architecture.md "Combat
modes"). A new mode is a new entry here, not an `if mode == ...` in the router."""

from dataclasses import dataclass
from typing import Literal

from app.combat.match import HOTSEAT, PVP


@dataclass(frozen=True, slots=True)
class ModePolicy:
    mode: str
    # What a player's "abandon" does: drop the fight without an outcome (hotseat), or
    # concede it so the opponent wins (online).
    abandon: Literal["close", "concede"]


POLICIES: dict[str, ModePolicy] = {
    p.mode: p for p in (ModePolicy(HOTSEAT, "close"), ModePolicy(PVP, "concede"))
}
