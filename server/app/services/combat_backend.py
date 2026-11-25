"""How the gateway reaches the combats: one interface, two implementations.

- `ProcessBackend` (production): combats live in worker processes, reached over IPC.
- `InProcessBackend` (tests): the same `CombatHost` code, in this process.

Both must pass the same contract tests (tests/services/test_combat_backend.py).
"""

from collections.abc import Callable
from typing import Any, Protocol

from app.combat.ground.ruleset import CombatRuleset
from app.persistence.combat_repo import CombatStore
from app.shared.clock import Clock
from app.workers import ipc
from app.workers.combat_host import CombatHost
from app.workers.supervisor import Supervisor

PushHandler = Callable[[str, str], None]  # (combat_id, CombatUpdate JSON text)


class CombatBackend(Protocol):
    @property
    def slots(self) -> int: ...

    def on_push(self, handler: PushHandler) -> None: ...

    def loads(self) -> list[int]:
        """Active combats per slot (placement). A combat counts from the moment
        `create()` is called, so a burst of creates spreads across slots."""
        ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def create(
        self,
        slot: int,
        combat_id: str,
        owner_user_id: int,
        mode: str,
        setup: dict[str, Any],
    ) -> dict[str, Any]:
        """Start a combat; returns its first snapshot (JSON)."""
        ...

    async def intent(
        self, slot: int, combat_id: str, user_id: int, intent: dict[str, Any]
    ) -> None: ...

    async def subscribe(
        self, slot: int, combat_id: str, user_id: int, last_seq: int | None
    ) -> dict[str, Any]: ...

    async def close(self, slot: int, combat_id: str, reason: str) -> None:
        """Mark an active combat `abandoned` and drop it from its worker."""
        ...


class ProcessBackend:
    def __init__(self, supervisor: Supervisor) -> None:
        self._supervisor = supervisor

    @property
    def slots(self) -> int:
        return self._supervisor.config.workers

    def on_push(self, handler: PushHandler) -> None:
        self._supervisor.on_push(handler)

    def loads(self) -> list[int]:
        return self._supervisor.loads()

    async def start(self) -> None:
        await self._supervisor.start()

    async def stop(self) -> None:
        await self._supervisor.stop()

    async def create(
        self,
        slot: int,
        combat_id: str,
        owner_user_id: int,
        mode: str,
        setup: dict[str, Any],
    ) -> dict[str, Any]:
        self._supervisor.adjust_load(slot, +1)  # counted from now (see the Protocol)
        try:
            payload = await self._supervisor.request(
                slot,
                lambda rid: ipc.Create(
                    request_id=rid,
                    combat_id=combat_id,
                    owner_user_id=owner_user_id,
                    mode=mode,
                    setup=setup,
                ),
            )
        except BaseException:
            self._supervisor.adjust_load(slot, -1)
            raise
        return payload or {}

    async def intent(
        self, slot: int, combat_id: str, user_id: int, intent: dict[str, Any]
    ) -> None:
        await self._supervisor.request(
            slot,
            lambda rid: ipc.Intent(
                request_id=rid, combat_id=combat_id, user_id=user_id, intent=intent
            ),
        )

    async def subscribe(
        self, slot: int, combat_id: str, user_id: int, last_seq: int | None
    ) -> dict[str, Any]:
        payload = await self._supervisor.request(
            slot,
            lambda rid: ipc.Subscribe(
                request_id=rid, combat_id=combat_id, user_id=user_id, last_seq=last_seq
            ),
        )
        return payload or {}

    async def close(self, slot: int, combat_id: str, reason: str) -> None:
        await self._supervisor.request(
            slot,
            lambda rid: ipc.Close(request_id=rid, combat_id=combat_id, reason=reason),
        )


class InProcessBackend:
    """Tests only: `slots` hosts in this process, sharing the gateway's event loop."""

    def __init__(
        self,
        ruleset: CombatRuleset,
        store: CombatStore,
        clock: Clock,
        *,
        slots: int = 2,
        idle_timeout_s: float = 24 * 3600,
    ) -> None:
        self._push: PushHandler = lambda combat_id, update: None
        self.hosts = [
            CombatHost(
                ruleset,
                store,
                slot=slot,
                publish=lambda combat_id, update: self._push(combat_id, update),
                clock=clock,
                idle_timeout_s=idle_timeout_s,
            )
            for slot in range(slots)
        ]
        self._placing = [0] * slots  # creates in flight, per slot

    @property
    def slots(self) -> int:
        return len(self.hosts)

    def on_push(self, handler: PushHandler) -> None:
        self._push = handler

    def loads(self) -> list[int]:
        return [
            host.load() + placing for host, placing in zip(self.hosts, self._placing)
        ]

    async def start(self) -> None:
        for host in self.hosts:
            await host.start()

    async def stop(self) -> None:
        for host in self.hosts:
            await host.drain()

    async def create(
        self,
        slot: int,
        combat_id: str,
        owner_user_id: int,
        mode: str,
        setup: dict[str, Any],
    ) -> dict[str, Any]:
        self._placing[slot] += 1  # counted from now (see the Protocol)
        try:
            return await self.hosts[slot].create(combat_id, owner_user_id, mode, setup)
        finally:
            self._placing[slot] -= 1

    async def intent(
        self, slot: int, combat_id: str, user_id: int, intent: dict[str, Any]
    ) -> None:
        await self.hosts[slot].intent(combat_id, user_id, intent)

    async def subscribe(
        self, slot: int, combat_id: str, user_id: int, last_seq: int | None
    ) -> dict[str, Any]:
        return await self.hosts[slot].subscribe(combat_id, user_id, last_seq)

    async def close(self, slot: int, combat_id: str, reason: str) -> None:
        await self.hosts[slot].close(combat_id, reason)
