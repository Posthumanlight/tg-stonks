"""Compile validated content into a ruleset: abilities bound to registered functions.

Every check that can fail does so here, at startup (docs/combat-ground.md "Load-time
checks"): unknown functions, wrong parameters, functions hooked into the wrong event,
missing ability parameters, unknown content ids.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.combat.ground import abilities as _library  # noqa: F401  (registers functions)
from app.combat.ground.abilities.params import Params
from app.combat.ground.abilities.registry import COMBINATORS, REGISTRY
from app.combat.ground.dice import Dice
from app.combat.ground.hooks import EVENTS, HookContext
from app.content.combat import (
    ARMOR_TYPES,
    DEFAULT_CONTENT_DIR,
    Ability,
    AbilityRef,
    CombatContent,
    FnCall,
    Unit,
    Weapon,
    content_hash,
    load_raw_combat_content,
    parse_combat_content,
)

DEFAULT_SCOPES = {
    "weapon": "weapon",
    "passive": "self",
    "status": "self",
    "active": "self",
}


class RulesetError(ValueError):
    """Content can't be compiled (bad function wiring or parameters)."""


@dataclass(frozen=True, slots=True)
class BoundFn:
    name: str
    func: Callable[[Any, Any], Any]
    params: Params

    def __call__(self, ctx: HookContext) -> Any:
        return self.func(ctx, self.params)


@dataclass(frozen=True, slots=True)
class BoundCombinator:
    mode: str  # all_of | any_of | not
    children: tuple["BoundFn | BoundCombinator", ...]

    def __call__(self, ctx: HookContext) -> bool:
        if self.mode == "all_of":
            return all(c(ctx) for c in self.children)
        if self.mode == "any_of":
            return any(c(ctx) for c in self.children)
        return not all(c(ctx) for c in self.children)


Condition = BoundFn | BoundCombinator


@dataclass(frozen=True, slots=True)
class BoundTrigger:
    event: str
    scope: str
    priority: int
    index: int
    conditions: tuple[Condition, ...]
    actions: tuple[BoundFn, ...]


@dataclass(frozen=True, slots=True)
class BoundAbility:
    ability_id: str
    definition: Ability
    params: dict[str, Any]
    triggers: tuple[BoundTrigger, ...]
    on_cast: tuple[BoundFn, ...]
    by_event: dict[str, tuple[BoundTrigger, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class CombatRuleset:
    content: CombatContent
    content_hash: str
    weapon_abilities: dict[str, tuple[BoundAbility, ...]]
    unit_abilities: dict[str, tuple[BoundAbility, ...]]
    statuses: dict[str, BoundAbility]

    @property
    def rules(self):  # noqa: ANN201 - RulesContent
        return self.content.rules

    def unit_def(self, unit_type: str) -> Unit:
        return self.content.units[unit_type]

    def weapon(self, weapon_id: str) -> Weapon:
        return self.content.weapons[weapon_id]

    def active_ability(self, unit_type: str, ability_id: str) -> BoundAbility | None:
        for bound in self.unit_abilities[unit_type]:
            if bound.ability_id == ability_id and bound.definition.kind == "active":
                return bound
        return None


# --- compilation -----------------------------------------------------------------------


def _convert_param(kind: str, value: Any, content: CombatContent) -> Any:
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise RulesetError(f"expected an integer, got {value!r}")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise RulesetError(f"expected a boolean, got {value!r}")
        return value
    if kind == "dice":
        try:
            return Dice.parse(value)
        except ValueError as exc:
            raise RulesetError(str(exc)) from exc
    known: Any = {
        "armor": ARMOR_TYPES,
        "tag": content.tags,
        "status": content.status_ids(),
        "terrain": content.terrain,
        "overlay": content.overlays,
        "unit_type": content.units,
        "weapon_type": content.weapon_types,
    }[kind]
    if value not in known:
        raise RulesetError(f"unknown {kind} {value!r}")
    return value


def _ability_params(
    ability: Ability, ref: AbilityRef, content: CombatContent
) -> dict[str, Any]:
    if missing := set(ability.params) - set(ref.params):
        raise RulesetError(f"missing params {sorted(missing)}")
    if extra := set(ref.params) - set(ability.params):
        raise RulesetError(f"unknown params {sorted(extra)}")
    return {
        name: _convert_param(kind, ref.params[name], content)
        for name, kind in ability.params.items()
    }


def _substitute(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        name = value[1:]
        if name not in params:
            raise RulesetError(f"unknown ability parameter {value!r}")
        found = params[name]
        return str(found) if isinstance(found, Dice) else found
    if isinstance(value, list):
        return [_substitute(v, params) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, params) for k, v in value.items()}
    return value


def _bind(
    call: FnCall,
    *,
    kind: str,
    event: str,
    params: dict[str, Any],
    content: CombatContent,
) -> Condition:
    args = _substitute(call.args, params)
    if call.fn in COMBINATORS:
        if kind != "condition":
            raise RulesetError(f"{call.fn!r} is a condition, not an action")
        if set(args) != {"conditions"} or not isinstance(args["conditions"], list):
            raise RulesetError(f"{call.fn!r} takes exactly `conditions = [...]`")
        children = tuple(
            _bind(
                FnCall.model_validate(c),
                kind=kind,
                event=event,
                params=params,
                content=content,
            )
            for c in args["conditions"]
        )
        if not children:
            raise RulesetError(f"{call.fn!r} needs at least one condition")
        return BoundCombinator(call.fn, children)
    spec = REGISTRY.get(call.fn)
    if spec is None:
        raise RulesetError(f"unknown function {call.fn!r}")
    if spec.kind != kind:
        raise RulesetError(f"{call.fn!r} is registered as {spec.kind}, used as {kind}")
    if spec.events is not None and event not in spec.events:
        raise RulesetError(f"{call.fn!r} can't be hooked into {event!r}")
    try:
        bound_params = spec.params.model_validate(args, context={"content": content})
    except ValidationError as exc:
        raise RulesetError(f"{call.fn!r}: {exc}") from exc
    return BoundFn(call.fn, spec.func, bound_params)


def bind_ability(ref: AbilityRef, content: CombatContent) -> BoundAbility:
    ability = content.abilities[ref.id]
    try:
        params = _ability_params(ability, ref, content)
        triggers = []
        for index, trigger in enumerate(ability.triggers):
            if trigger.event not in EVENTS:
                raise RulesetError(f"unknown event {trigger.event!r}")
            scope = trigger.scope or DEFAULT_SCOPES[ability.kind]
            if (scope == "weapon") != (ability.kind == "weapon"):
                raise RulesetError("scope 'weapon' is exactly for weapon abilities")
            common = {"event": trigger.event, "params": params, "content": content}
            triggers.append(
                BoundTrigger(
                    event=trigger.event,
                    scope=scope,
                    priority=trigger.priority,
                    index=index,
                    conditions=tuple(
                        _bind(c, kind="condition", **common) for c in trigger.conditions
                    ),
                    actions=tuple(_bind(a, kind="action", **common) for a in trigger.actions),  # type: ignore[misc]
                )
            )
        on_cast = tuple(
            _bind(
                a, kind="action", event="ability_cast", params=params, content=content
            )
            for a in ability.on_cast
        )
    except RulesetError as exc:
        raise RulesetError(f"ability {ref.id!r}: {exc}") from exc
    by_event: dict[str, list[BoundTrigger]] = {}
    for trig in triggers:
        by_event.setdefault(trig.event, []).append(trig)
    return BoundAbility(
        ability_id=ref.id,
        definition=ability,
        params=params,
        triggers=tuple(triggers),
        on_cast=on_cast,  # type: ignore[arg-type]
        by_event={k: tuple(v) for k, v in by_event.items()},
    )


def compile_ruleset(content: CombatContent, digest: str) -> CombatRuleset:
    def bind_all(where: str, refs: tuple[AbilityRef, ...]) -> tuple[BoundAbility, ...]:
        try:
            return tuple(bind_ability(ref, content) for ref in refs)
        except RulesetError as exc:
            raise RulesetError(f"{where}: {exc}") from exc

    return CombatRuleset(
        content=content,
        content_hash=digest,
        weapon_abilities={
            wid: bind_all(f"weapon {wid!r}", w.abilities)
            for wid, w in content.weapons.items()
        },
        unit_abilities={
            uid: bind_all(f"unit {uid!r}", u.abilities)
            for uid, u in content.units.items()
        },
        statuses={
            sid: bind_ability(AbilityRef(id=sid), content)
            for sid in sorted(content.status_ids())
        },
    )


def ruleset_from_raw(raw: dict[str, Any]) -> CombatRuleset:
    return compile_ruleset(parse_combat_content(raw), content_hash(raw))


def load_ruleset(directory: Path = DEFAULT_CONTENT_DIR) -> CombatRuleset:
    """Load, validate and compile `content/combat/`. Call once at startup."""
    return ruleset_from_raw(load_raw_combat_content(directory))
