"""The combats living in one worker: lifecycle, persistence, recovery.

Transport-agnostic: results go back as return values or GameError, and updates go out
through the injected `publish` callback (IPC in a worker process, a direct call in the
in-process test backend).

Recovery is lazy: after a (re)start a combat is replayed from its record the first time
it's touched, so start-up time doesn't grow with the number of fights in flight.
"""

import asyncio
import logging
import secrets
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from app.combat.ground.engine import COMBAT_RULES_VERSION, IllegalAction
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.serialize import action_from_json, setup_from_json
from app.combat.ground.setup import SetupError
from app.persistence.combat_repo import ACTIVE, ActionRow, CombatStore, NewCombat
from app.persistence.write_behind import WriteBehindBuffer
from app.protocol.combat import CombatIntentEnvelope
from app.shared.clock import Clock
from app.shared.errors import GameError
from app.workers.combat_instance import CombatInstance

log = logging.getLogger(__name__)

# (combat_id, CombatUpdate as JSON text). Serialized once here; the gateway forwards
# the text into WebSocket frames without parsing it.
Publish = Callable[[str, str], None]

CATCH_UP_LIMIT = 500  # beyond this many missed events a client gets a snapshot
FINISHED_GRACE_S = 600  # finished combats stay viewable this long


class CombatHost:
    def __init__(
        self,
        ruleset: CombatRuleset,
        store: CombatStore,
        *,
        slot: int,
        publish: Publish,
        clock: Clock,
        idle_timeout_s: float,
        flush_interval_s: float = 1.0,
    ) -> None:
        self.ruleset = ruleset
        self.store = store
        self.slot = slot
        self._publish = publish
        self._clock = clock
        self._idle_timeout = idle_timeout_s
        self.instances: dict[str, CombatInstance] = {}
        self._last_activity: dict[str, float] = {}
        self._loading: dict[str, asyncio.Task[CombatInstance]] = {}
        self.writes: WriteBehindBuffer[ActionRow] = WriteBehindBuffer(
            store.append_actions, interval_s=flush_interval_s
        )

    # --- lifecycle ---------------------------------------------------------------------

    def load(self) -> int:
        return sum(1 for i in self.instances.values() if not i.finished)

    async def create(
        self, combat_id: str, owner_user_id: int, mode: str, setup_json: dict[str, Any]
    ) -> dict[str, Any]:
        """Start a combat and persist its record. Returns the first snapshot (JSON)."""
        seed = secrets.randbits(63)  # randomness comes from the shell, never the engine
        try:
            instance = CombatInstance(
                combat_id,
                owner_user_id,
                mode,
                self.ruleset,
                setup_from_json(setup_json),
                seed,
            )
        except (SetupError, KeyError, TypeError, ValueError) as exc:
            raise GameError("combat.bad_setup", 400, detail=str(exc)) from exc
        await self.store.create(
            NewCombat(
                combat_id=combat_id,
                owner_user_id=owner_user_id,
                mode=mode,
                worker_slot=self.slot,
                setup=setup_json,
                seed=seed,
                content_hash=self.ruleset.content_hash,
                rules_version=COMBAT_RULES_VERSION,
            )
        )
        self._register(instance)
        return instance.snapshot().model_dump(mode="json")

    async def start(self) -> int:
        """Prepare this slot after a (re)start: abort records that can't be replayed
        (content or rules changed). Returns how many. Nothing is loaded here."""
        return await self.store.abort_incompatible(
            self.slot, self.ruleset.content_hash, COMBAT_RULES_VERSION
        )

    async def drain(self) -> None:
        """Before shutdown: everything pending reaches the DB."""
        await self.writes.flush()

    async def sweep(self) -> None:
        """Abandon idle combats; forget finished ones after a grace period."""
        now = self._clock.monotonic()
        for combat_id, instance in list(self.instances.items()):
            idle = now - self._last_activity.get(combat_id, now)
            if instance.finished and idle > FINISHED_GRACE_S:
                self._forget(combat_id)
            elif not instance.finished and idle > self._idle_timeout:
                await self.writes.flush()
                await self.store.mark(combat_id, "abandoned", reason="idle")
                self._forget(combat_id)

    async def close(self, combat_id: str, reason: str) -> None:
        """End an active combat without an outcome (the owner abandoned it). This host
        is the combat's only status writer, so pending actions are flushed first and a
        finish can't race the mark. Works whether or not the combat is resident."""
        await self.writes.flush()
        await self.store.mark(combat_id, "abandoned", reason=reason)
        self._forget(combat_id)

    # --- requests ----------------------------------------------------------------------

    async def intent(
        self, combat_id: str, user_id: int, intent_json: dict[str, Any]
    ) -> None:
        instance = await self._get(combat_id)
        try:
            intent = CombatIntentEnvelope.model_validate({"intent": intent_json}).intent
        except ValidationError as exc:
            raise GameError("request.invalid", 400) from exc
        result = instance.handle(user_id, intent)  # raises GameError when refused
        self._touch(combat_id)
        self.writes.add(ActionRow(combat_id, result.action_seq, result.action))
        self._publish(combat_id, result.update.model_dump_json())
        if result.finished:
            await self.writes.flush()
            await self.store.mark(
                combat_id, "finished", outcome=instance.outcome_json()
            )

    async def subscribe(
        self, combat_id: str, user_id: int, last_seq: int | None
    ) -> dict[str, Any]:
        """Events since `last_seq`, or a full snapshot (JSON). Only for participants."""
        instance = await self._get(combat_id)
        if not instance.seated(user_id):
            raise GameError("combat.not_a_participant", 403)
        self._touch(combat_id)
        update = instance.catch_up(last_seq, CATCH_UP_LIMIT)
        if update is not None:
            return {"kind": "events", "update": update.model_dump(mode="json")}
        return {
            "kind": "snapshot",
            "snapshot": instance.snapshot().model_dump(mode="json"),
        }

    # --- internals ---------------------------------------------------------------------

    async def _get(self, combat_id: str) -> CombatInstance:
        """The live instance, replaying it from its record on first touch."""
        instance = self.instances.get(combat_id)
        if instance is not None:
            return instance
        loading = self._loading.get(combat_id)
        if loading is None:  # concurrent first touches share one load
            loading = asyncio.ensure_future(self._load(combat_id))
            self._loading[combat_id] = loading
            loading.add_done_callback(lambda _: self._loading.pop(combat_id, None))
        return await asyncio.shield(loading)

    async def _load(self, combat_id: str) -> CombatInstance:
        stored = await self.store.load(combat_id)
        if stored is None or stored.status != ACTIVE or stored.worker_slot != self.slot:
            raise GameError("combat.not_found", 404)
        if (
            stored.content_hash != self.ruleset.content_hash
            or stored.rules_version != COMBAT_RULES_VERSION
        ):
            await self.store.mark(
                combat_id, "aborted", reason="content or rules changed"
            )
            raise GameError("combat.not_found", 404)
        try:
            instance = CombatInstance(
                stored.combat_id,
                stored.owner_user_id,
                stored.mode,
                self.ruleset,
                setup_from_json(stored.setup),
                stored.seed,
                actions=[action_from_json(a) for a in stored.actions],
            )
        except (IllegalAction, SetupError, KeyError, TypeError, ValueError) as exc:
            log.exception("combat %s can't be replayed", combat_id)
            await self.store.mark(combat_id, "aborted", reason=f"replay failed: {exc}")
            raise GameError("combat.not_found", 404) from exc
        # A create() for the same id can't race this: ids are fresh UUIDs.
        self._register(instance)
        return instance

    def _register(self, instance: CombatInstance) -> None:
        self.instances[instance.combat_id] = instance
        self._touch(instance.combat_id)

    def _touch(self, combat_id: str) -> None:
        self._last_activity[combat_id] = self._clock.monotonic()

    def _forget(self, combat_id: str) -> None:
        self.instances.pop(combat_id, None)
        self._last_activity.pop(combat_id, None)
