"""Rounds, queues, Wait and the end of combat (docs/combat-ground.md "Turn structure")."""

from dataclasses import replace
from typing import TYPE_CHECKING

from app.combat.ground import events as ev
from app.combat.ground import hooks
from app.combat.ground.state import (
    Activation,
    OverlayState,
    Outcome,
    StatusState,
    UnitId,
)

if TYPE_CHECKING:
    from app.combat.ground.resolver import Resolver


def begin_round(res: "Resolver") -> None:
    res.state = replace(res.state, round=res.state.round + 1)
    _tick_durations(res)
    for unit in res.state.living():
        res.update_unit(
            unit.uid, reactions=res.effective_stat(unit.uid, "reactions"), waited=False
        )
    ranks = {side: i for i, side in enumerate(res.state.tie_order())}
    order = tuple(
        u.uid
        for u in sorted(
            res.state.living(),
            key=lambda u: (
                -res.effective_stat(u.uid, "speed"),
                ranks.get(u.side, 0),
                u.uid,
            ),
        )
    )
    res.state = replace(res.state, round_order=order, queue=order, wait_queue=())
    res.emit(ev.RoundStarted(res.state.round, order))
    res.dispatch(hooks.RoundStarted(res))


def _tick_durations(res: "Resolver") -> None:
    expired: list[tuple[UnitId, str]] = []
    for unit in res.state.units:
        if not unit.alive:
            continue
        statuses: list[StatusState] = []
        for status in unit.statuses:
            if status.rounds_left > 1:
                statuses.append(replace(status, rounds_left=status.rounds_left - 1))
            else:
                expired.append((unit.uid, status.status))
        cooldowns = tuple((a, n - 1) for a, n in unit.cooldowns if n > 1)
        res.update_unit(unit.uid, statuses=tuple(statuses), cooldowns=cooldowns)
    overlays: list[OverlayState] = []
    for overlay in res.state.overlays:
        if overlay.rounds_left > 1:
            overlays.append(replace(overlay, rounds_left=overlay.rounds_left - 1))
        else:
            res.emit(ev.OverlayExpired(overlay.square, overlay.overlay))
    res.state = replace(res.state, overlays=tuple(overlays))
    for uid, status in expired:
        res.emit(ev.StatusExpired(uid, status))
        res.dispatch(hooks.StatusExpired(res, unit=uid, status=status))


def begin_activation(res: "Resolver", uid: UnitId) -> None:
    movement = res.effective_stat(uid, "movement")
    action_points = res.effective_stat(uid, "action_points")
    res.state = replace(res.state, active=Activation(uid, movement, action_points))
    res.end_requested = False
    res.emit(ev.ActivationStarted(uid, movement, action_points))
    res.dispatch(hooks.ActivationStarted(res, unit=uid))


def end_activation(res: "Resolver") -> None:
    active = res.state.active
    if active is None:
        return
    res.emit(ev.ActivationEnded(active.uid))
    res.dispatch(hooks.ActivationEnded(res, unit=active.uid))
    res.state = replace(res.state, active=None)
    res.end_requested = False


def can_wait(res: "Resolver") -> bool:
    active = res.state.active
    return (
        active is not None
        and not active.acted
        and not res.state.unit(active.uid).waited
    )


def wait(res: "Resolver") -> None:
    """Send the active unit to the wait queue (slowest waiter acts first)."""
    active = res.state.active
    assert active is not None
    uid = active.uid
    res.update_unit(uid, waited=True)
    res.state = replace(res.state, active=None)
    position = {u: i for i, u in enumerate(res.state.round_order)}

    def key(u: UnitId) -> tuple[int, int]:
        return (res.effective_stat(u, "speed"), -position.get(u, len(position) + u))

    waiting = sorted(res.state.wait_queue + (uid,), key=key)
    res.state = replace(res.state, wait_queue=tuple(waiting))
    res.emit(ev.UnitWaited(uid))
    res.dispatch(hooks.UnitWaited(res, unit=uid))


def next_unit(res: "Resolver") -> UnitId | None:
    """Pop the next living unit from the main queue, then the wait queue."""
    while res.state.queue or res.state.wait_queue:
        if res.state.queue:
            uid, rest = res.state.queue[0], res.state.queue[1:]
            res.state = replace(res.state, queue=rest)
        else:
            uid, rest = res.state.wait_queue[0], res.state.wait_queue[1:]
            res.state = replace(res.state, wait_queue=rest)
        if res.state.unit(uid).alive:
            return uid
    return None


def end_round(res: "Resolver") -> None:
    res.dispatch(hooks.RoundEnded(res))
    res.emit(ev.RoundEnded(res.state.round))
    if res.state.outcome is None and res.state.round >= res.ruleset.rules.round_limit:
        _finish_on_points(res)


def check_annihilation(res: "Resolver") -> bool:
    if res.state.outcome is not None:
        return True
    sides = res.state.sides_alive()
    if len(sides) <= 1:
        finish(res, Outcome(winners=sides, draw=not sides, reason="annihilation"))
        return True
    return False


def side_points(res: "Resolver") -> dict[int, int]:
    """Surviving points per side: unit points scaled by surviving models."""
    points = {side: 0 for side in res.state.side_order}
    for unit in res.state.units:
        definition = res.ruleset.unit_def(unit.unit_type)
        points[unit.side] = points.get(unit.side, 0) + (
            definition.points * unit.models // max(1, unit.initial_models)
        )
    return points


def _finish_on_points(res: "Resolver") -> None:
    points = side_points(res)
    top = max(points.values())
    margin = res.ruleset.rules.draw_margin_percent
    contenders = tuple(
        sorted(side for side, p in points.items() if (top - p) * 100 <= margin * top)
    )
    finish(
        res,
        Outcome(winners=contenders, draw=len(contenders) != 1, reason="round_limit"),
    )


def finish(res: "Resolver", outcome: Outcome) -> None:
    res.state = replace(
        res.state, outcome=outcome, active=None, queue=(), wait_queue=()
    )
    res.emit(ev.CombatEnded(outcome.winners, outcome.draw, outcome.reason))
