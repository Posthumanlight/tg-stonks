"""Custom battles at the gateway: the builder data and turning a request into a
validated setup (docs/architecture.md "Custom battle flow").

Validation runs here, in the gateway, so a bad setup never reaches a worker; the worker
still re-runs the engine's own checks when it starts the combat.
"""

from typing import Any

from app.api.static_json import StaticJson
from app.combat.ground.deployment import BattleMap, deploy
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.serialize import setup_to_json
from app.combat.ground.setup import SetupError
from app.protocol.builder import CustomCombatRequest, armies_from_request, builder_view
from app.shared.errors import from_setup_error


class CustomBattles:
    def __init__(self, ruleset: CombatRuleset, battle_map: BattleMap) -> None:
        self._ruleset = ruleset
        self._map = battle_map
        self.builder = StaticJson.of(builder_view(ruleset, battle_map))
        self.default_setup = setup_to_json(
            deploy(ruleset, battle_map, battle_map.defaults)
        )

    def setup_for(self, request: CustomCombatRequest) -> dict[str, Any]:
        """The request as a validated setup (JSON), or a located `setup.*` GameError."""
        try:
            setup = deploy(self._ruleset, self._map, armies_from_request(request))
        except SetupError as exc:
            raise from_setup_error(exc) from exc
        return setup_to_json(setup)
