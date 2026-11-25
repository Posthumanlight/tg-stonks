"""Combat records store. Narrow and async; each call is one transaction."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import Combat, CombatAction

ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class NewCombat:
    combat_id: str
    owner_user_id: int
    mode: str
    worker_slot: int
    setup: dict[str, Any]
    seed: int
    content_hash: str
    rules_version: int


@dataclass(frozen=True, slots=True)
class StoredCombat:
    combat_id: str
    owner_user_id: int
    mode: str
    status: str
    worker_slot: int
    setup: dict[str, Any]
    seed: int
    content_hash: str
    rules_version: int
    actions: tuple[dict[str, Any], ...]  # by seq


@dataclass(frozen=True, slots=True)
class CombatSummary:
    combat_id: str
    mode: str
    status: str
    worker_slot: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActionRow:
    combat_id: str
    seq: int
    action: dict[str, Any]


class CombatStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, combat: NewCombat) -> None:
        async with self._sessions() as session:
            session.add(
                Combat(
                    combat_id=uuid.UUID(combat.combat_id),
                    owner_user_id=combat.owner_user_id,
                    mode=combat.mode,
                    status=ACTIVE,
                    worker_slot=combat.worker_slot,
                    setup=combat.setup,
                    seed=combat.seed,
                    content_hash=combat.content_hash,
                    rules_version=combat.rules_version,
                )
            )
            await session.commit()

    async def append_actions(self, rows: Sequence[ActionRow]) -> None:
        """One batch, one transaction (write-behind flush)."""
        if not rows:
            return
        async with self._sessions() as session:
            await session.execute(
                insert(CombatAction),
                [
                    {
                        "combat_id": uuid.UUID(r.combat_id),
                        "seq": r.seq,
                        "action": r.action,
                    }
                    for r in rows
                ],
            )
            await session.commit()

    async def mark(
        self,
        combat_id: str,
        status: str,
        *,
        outcome: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status, "status_reason": reason}
        if outcome is not None:
            values["outcome"] = outcome
        if status != ACTIVE:
            values["finished_at"] = datetime.now(UTC)
        async with self._sessions() as session:
            await session.execute(
                update(Combat)
                .where(Combat.combat_id == uuid.UUID(combat_id))
                .values(**values)
            )
            await session.commit()

    async def load(self, combat_id: str) -> StoredCombat | None:
        """One combat's full record (setup + actions), for lazy recovery."""
        async with self._sessions() as session:
            combat = await session.get(Combat, uuid.UUID(combat_id))
            return await _stored(session, combat) if combat else None

    async def load_active(self, slot: int) -> list[StoredCombat]:
        async with self._sessions() as session:
            combats = (
                await session.scalars(
                    select(Combat)
                    .where(Combat.status == ACTIVE, Combat.worker_slot == slot)
                    .order_by(Combat.created_at, Combat.combat_id)
                )
            ).all()
            return [await _stored(session, combat) for combat in combats]

    async def abort_incompatible(
        self, slot: int, content_hash: str, rules_version: int
    ) -> int:
        """Abort this slot's active combats recorded under other content or rules
        (they can't be replayed). One statement: no records are loaded."""
        async with self._sessions() as session:
            result = await session.execute(
                update(Combat)
                .where(
                    Combat.status == ACTIVE,
                    Combat.worker_slot == slot,
                    (Combat.content_hash != content_hash)
                    | (Combat.rules_version != rules_version),
                )
                .values(
                    status="aborted",
                    status_reason="content or rules changed",
                    finished_at=datetime.now(UTC),
                )
            )
            await session.commit()
            return result.rowcount or 0

    async def active_for_owner(
        self, owner_user_id: int, mode: str
    ) -> CombatSummary | None:
        found = await self.list_for_owner(owner_user_id, status=ACTIVE, mode=mode)
        return found[0] if found else None

    async def list_for_owner(
        self, owner_user_id: int, *, status: str | None = None, mode: str | None = None
    ) -> list[CombatSummary]:
        query = select(Combat).where(Combat.owner_user_id == owner_user_id)
        if status is not None:
            query = query.where(Combat.status == status)
        if mode is not None:
            query = query.where(Combat.mode == mode)
        async with self._sessions() as session:
            rows = (
                await session.scalars(query.order_by(Combat.created_at.desc()))
            ).all()
            return [
                CombatSummary(
                    str(c.combat_id), c.mode, c.status, c.worker_slot, c.created_at
                )
                for c in rows
            ]

    async def slot_of(self, combat_id: str) -> int | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(Combat.worker_slot).where(
                    Combat.combat_id == uuid.UUID(combat_id), Combat.status == ACTIVE
                )
            )

    async def fold_slots(self, workers: int) -> None:
        """Re-home active combats when the worker count shrank between restarts."""
        async with self._sessions() as session:
            await session.execute(
                update(Combat)
                .where(Combat.status == ACTIVE, Combat.worker_slot >= workers)
                .values(worker_slot=Combat.worker_slot % workers)
            )
            await session.commit()


async def _stored(session: AsyncSession, combat: Combat) -> StoredCombat:
    actions = (
        await session.scalars(
            select(CombatAction.action)
            .where(CombatAction.combat_id == combat.combat_id)
            .order_by(CombatAction.seq)
        )
    ).all()
    return StoredCombat(
        combat_id=str(combat.combat_id),
        owner_user_id=combat.owner_user_id,
        mode=combat.mode,
        status=combat.status,
        worker_slot=combat.worker_slot,
        setup=combat.setup,
        seed=combat.seed,
        content_hash=combat.content_hash,
        rules_version=combat.rules_version,
        actions=tuple(actions),
    )
