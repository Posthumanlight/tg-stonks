"""Combat worker process: hosts combats for one slot and talks to the gateway over IPC.

Started by the supervisor (multiprocessing, spawn context) with a `WorkerConfig`; it
builds its own DB engine and ruleset (the worker's composition root).
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.combat.ground.ruleset import load_ruleset
from app.persistence.combat_repo import CombatStore
from app.persistence.db import create_engine
from app.shared.clock import SystemClock
from app.shared.dispatch import Dispatcher
from app.shared.errors import GameError
from app.workers import ipc
from app.workers.combat_host import CombatHost

log = logging.getLogger(__name__)

LOAD_REPORT_INTERVAL_S = 5.0
SWEEP_INTERVAL_S = 60.0


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    slot: int
    port: int
    boot_token: str
    database_url: str
    pool_size: int
    idle_timeout_s: float
    flush_interval_s: float


def main(config: WorkerConfig) -> None:
    logging.basicConfig(
        level=logging.INFO, format=f"[worker {config.slot}] %(levelname)s %(message)s"
    )
    asyncio.run(serve(config))


def build_dispatcher(host: CombatHost) -> Dispatcher[None]:
    dispatcher: Dispatcher[None] = Dispatcher()

    @dispatcher.on("create")
    async def create(_: None, msg: ipc.Create) -> dict:
        return await host.create(msg.combat_id, msg.owner_user_id, msg.mode, msg.setup)

    @dispatcher.on("intent")
    async def intent(_: None, msg: ipc.Intent) -> None:
        await host.intent(msg.combat_id, msg.user_id, msg.intent)

    @dispatcher.on("subscribe")
    async def subscribe(_: None, msg: ipc.Subscribe) -> dict:
        return await host.subscribe(msg.combat_id, msg.user_id, msg.last_seq)

    return dispatcher


async def _every(interval_s: float, job) -> None:  # noqa: ANN001
    while True:
        await asyncio.sleep(interval_s)
        try:
            await job()
        except Exception:
            log.exception("periodic job failed")


async def serve(config: WorkerConfig) -> None:
    engine = create_engine(config.database_url, pool_size=config.pool_size)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    reader, writer = await asyncio.open_connection("127.0.0.1", config.port)
    channel = ipc.IpcChannel(reader, writer)

    host = CombatHost(
        load_ruleset(),
        CombatStore(sessions),
        slot=config.slot,
        publish=lambda combat_id, update: channel.write(
            ipc.Pushed(combat_id=combat_id, update=update)
        ),
        clock=SystemClock(),
        idle_timeout_s=config.idle_timeout_s,
        flush_interval_s=config.flush_interval_s,
    )
    aborted = await host.start()  # combats are replayed lazily, on first touch
    log.info("slot %d ready (%d incompatible combats aborted)", config.slot, aborted)
    await channel.send(ipc.Hello(slot=config.slot, boot_token=config.boot_token))

    async def report_load() -> None:
        await channel.send(ipc.LoadReport(instances=host.load()))

    tasks = [
        asyncio.create_task(host.writes.run()),
        asyncio.create_task(_every(SWEEP_INTERVAL_S, host.sweep)),
        asyncio.create_task(_every(LOAD_REPORT_INTERVAL_S, report_load)),
    ]
    dispatcher = build_dispatcher(host)
    try:
        await report_load()
        while True:
            try:
                msg = await channel.recv()
            except (asyncio.IncompleteReadError, ConnectionError):
                break  # the gateway went away
            if isinstance(msg, ipc.Ping):
                channel.write(ipc.Pong())
            elif isinstance(msg, ipc.Drain):
                break
            elif dispatcher.handles(msg.type):
                channel.write(await _handle(dispatcher, msg))
            await channel.drain()
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        with contextlib.suppress(Exception):
            await host.drain()
        channel.close()
        await engine.dispose()


async def _handle(dispatcher: Dispatcher[None], msg) -> ipc.Reply:  # noqa: ANN001
    try:
        payload = await dispatcher.dispatch(msg.type, None, msg)
        return ipc.Reply(request_id=msg.request_id, ok=True, payload=payload)
    except GameError as exc:
        return ipc.Reply(
            request_id=msg.request_id,
            ok=False,
            reason_key=exc.reason_key,
            status=exc.status,
        )
    except Exception:
        log.exception("request %s failed", msg.type)
        return ipc.Reply(
            request_id=msg.request_id,
            ok=False,
            reason_key="combat.internal",
            status=500,
        )
