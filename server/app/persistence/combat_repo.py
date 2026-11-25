"""Combat records store. Narrow and async; each call is one transaction."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.combat.match import Match, Seat
from app.persistence.models import Combat, CombatAction, CombatSeat

ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class NewCombat:
    combat_id: str
    match: Match
    worker_slot: int
    setup: dict[str, Any]
    seed: int
    content_hash: str
    rules_version: int


@dataclass(frozen=True, slots=True)
class StoredCombat:
    combat_id: str
    match: Match
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
    owner_user_id: int
    mode: str
    status: str
    worker_slot: int
    created_at: datetime

    @classmethod
    def of(cls, c: Combat) -> "CombatSummary":
        return cls(
            str(c.combat_id),
            c.owner_user_id,
            c.mode,
            c.status,
            c.worker_slot,
            c.created_at,
        )


@dataclass(frozen=True, slots=True)
class ActionRow:
    combat_id: str
    seq: int
    action: dict[str, Any]


class CombatStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, combat: NewCombat) -> None:
        """The combat row and its seats, in one transaction."""
        match, key = combat.match, uuid.UUID(combat.combat_id)
        async with self._sessions() as session:
            session.add(
                Combat(
                    combat_id=key,
                    owner_user_id=match.owner_user_id,
                    mode=match.mode,
                    status=ACTIVE,
                    worker_slot=combat.worker_slot,
                    setup=combat.setup,
                    seed=combat.seed,
                    content_hash=combat.content_hash,
                    rules_version=combat.rules_version,
                    activation_timer_s=match.timer_s,
                )
            )
            await session.flush()  # the seats reference the combat row
            session.add_all(
                CombatSeat(combat_id=key, side=s.side, user_id=s.user_id, name=s.name)
                for s in match.seats
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

    async def active_for_user(self, user_id: int, mode: str) -> CombatSummary | None:
        found = await self.list_for_user(user_id, status=ACTIVE, mode=mode)
        return found[0] if found else None

    async def list_for_user(
        self, user_id: int, *, status: str | None = None, mode: str | None = None
    ) -> list[CombatSummary]:
        """The user's combats, newest first: the ones they own or hold a seat in."""
        seated = select(CombatSeat.combat_id).where(CombatSeat.user_id == user_id)
        query = select(Combat).where(
            or_(Combat.owner_user_id == user_id, Combat.combat_id.in_(seated))
        )
        if status is not None:
            query = query.where(Combat.status == status)
        if mode is not None:
            query = query.where(Combat.mode == mode)
        async with self._sessions() as session:
            rows = (
                await session.scalars(query.order_by(Combat.created_at.desc()))
            ).all()
            return [CombatSummary.of(c) for c in rows]

    async def participants(self, combat_id: str) -> frozenset[int]:
        """Everyone seated in the combat, plus its owner."""
        key = uuid.UUID(combat_id)
        async with self._sessions() as session:
            combat = await session.get(Combat, key)
            if combat is None:
                return frozenset()
            seated = await session.scalars(
                select(CombatSeat.user_id).where(CombatSeat.combat_id == key)
            )
            return frozenset({combat.owner_user_id, *seated})

    async def summary(self, combat_id: str) -> CombatSummary | None:
        """One combat's row without its record (ownership and status checks)."""
        try:
            key = uuid.UUID(combat_id)
        except ValueError:
            return None
        async with self._sessions() as session:
            combat = await session.get(Combat, key)
            return CombatSummary.of(combat) if combat else None

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
    seats = (
        await session.scalars(
            select(CombatSeat)
            .where(CombatSeat.combat_id == combat.combat_id)
            .order_by(CombatSeat.side)
        )
    ).all()
    return StoredCombat(
        combat_id=str(combat.combat_id),
        match=Match(
            combat.owner_user_id,
            combat.mode,
            tuple(Seat(s.side, s.user_id, s.name) for s in seats),
            combat.activation_timer_s,
        ),
        status=combat.status,
        worker_slot=combat.worker_slot,
        setup=combat.setup,
        seed=combat.seed,
        content_hash=combat.content_hash,
        rules_version=combat.rules_version,
        actions=tuple(actions),
    )
