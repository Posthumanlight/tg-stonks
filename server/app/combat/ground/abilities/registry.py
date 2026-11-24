"""Registry of hookable Python functions: `@condition` and `@action`.

Content wires these by name into ability triggers (docs/combat-ground.md "Abilities").
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from app.combat.ground.abilities.params import NoParams, Params
from app.combat.ground.hooks import EVENTS

FnKind = Literal["condition", "action"]

# Built-in condition combinators, compiled specially (they nest other conditions).
COMBINATORS: frozenset[str] = frozenset({"all_of", "any_of", "not"})


@dataclass(frozen=True, slots=True)
class FnSpec:
    name: str
    kind: FnKind
    func: Callable[[Any, Any], Any]
    params: type[Params]
    events: frozenset[str] | None  # None = allowed in any event


REGISTRY: dict[str, FnSpec] = {}


def _register(
    kind: FnKind, name: str, params: type[Params], events: Iterable[str] | None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    allowed = None if events is None else frozenset(events)
    if allowed is not None and (unknown := allowed - EVENTS):
        raise ValueError(f"{name}: unknown events {sorted(unknown)}")
    if name in COMBINATORS:
        raise ValueError(f"{name!r} is a reserved combinator name")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if name in REGISTRY:
            raise ValueError(f"function {name!r} registered twice")
        REGISTRY[name] = FnSpec(name, kind, func, params, allowed)
        return func

    return decorator


def condition(
    name: str, *, params: type[Params] = NoParams, events: Iterable[str] | None = None
) -> Callable[[Callable[..., bool]], Callable[..., bool]]:
    """Register `func(ctx, params) -> bool`."""
    return _register("condition", name, params, events)


def action(
    name: str, *, params: type[Params] = NoParams, events: Iterable[str] | None = None
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """Register `func(ctx, params) -> None`."""
    return _register("action", name, params, events)
