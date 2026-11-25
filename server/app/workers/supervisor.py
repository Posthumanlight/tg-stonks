"""Gateway side of the worker processes: spawn, connect, request/reply, health, restart.

Workers connect back to a localhost listener and must present the per-boot token.
A lost worker fails its in-flight requests with `combat.unavailable`, is restarted with
backoff; the new worker replays each of its combats from the DB on first touch.
"""

import asyncio
import contextlib
import itertools
import logging
import multiprocessing
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.shared.clock import Clock
from app.shared.errors import GameError
from app.workers import ipc
from app.workers.combat_worker import WorkerConfig, main as worker_main

log = logging.getLogger(__name__)

PushHandler = Callable[[str, str], None]  # (combat_id, CombatUpdate JSON text)

REQUEST_TIMEOUT_S = 15.0
READY_TIMEOUT_S = 60.0
PING_INTERVAL_S = 5.0
PING_TIMEOUT_S = 15.0
MAX_BACKOFF_S = 30.0


@dataclass(frozen=True, slots=True)
class SupervisorConfig:
    workers: int
    database_url: str
    pool_size: int
    idle_timeout_s: float
    flush_interval_s: float = 1.0


@dataclass
class _Worker:
    slot: int
    process: multiprocessing.process.BaseProcess | None = None
    channel: ipc.IpcChannel | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    pending: dict[int, asyncio.Future[ipc.Reply]] = field(default_factory=dict)
    load: int = 0
    last_pong: float = 0.0
    backoff_s: float = 1.0
    restarting: bool = False


def _unavailable() -> GameError:
    return GameError("combat.unavailable", 503)


class Supervisor:
    def __init__(self, config: SupervisorConfig, clock: Clock) -> None:
        self.config = config
        self._clock = clock
        self._workers = [_Worker(slot) for slot in range(config.workers)]
        self._push: PushHandler = lambda combat_id, update: None
        self._ids = itertools.count(1)
        self._token = secrets.token_urlsafe(32)
        self._server: asyncio.Server | None = None
        self._port = 0
        self._monitor: asyncio.Task[None] | None = None
        self._stopping = False

    def on_push(self, handler: PushHandler) -> None:
        self._push = handler

    def loads(self) -> list[int]:
        return [w.load if w.ready.is_set() else 1 << 30 for w in self._workers]

    def adjust_load(self, slot: int, delta: int) -> None:
        """Count a placement now; the worker's next load report replaces the estimate.
        Without this, every combat created between two reports lands on one worker."""
        worker = self._workers[slot]
        worker.load = max(0, worker.load + delta)

    # --- lifecycle ---------------------------------------------------------------------

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._on_connect, "127.0.0.1", 0)
        self._port = self._server.sockets[0].getsockname()[1]
        for worker in self._workers:
            self._spawn(worker)
        await asyncio.wait_for(
            asyncio.gather(*(w.ready.wait() for w in self._workers)), READY_TIMEOUT_S
        )
        self._monitor = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        self._stopping = True
        if self._monitor is not None:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
        for worker in self._workers:
            if worker.channel is not None:
                with contextlib.suppress(Exception):
                    await worker.channel.send(ipc.Drain())
        for worker in self._workers:
            if worker.process is not None:
                await asyncio.to_thread(worker.process.join, 10)
                if worker.process.is_alive():
                    worker.process.terminate()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def _spawn(self, worker: _Worker) -> None:
        config = WorkerConfig(
            slot=worker.slot,
            port=self._port,
            boot_token=self._token,
            database_url=self.config.database_url,
            pool_size=self.config.pool_size,
            idle_timeout_s=self.config.idle_timeout_s,
            flush_interval_s=self.config.flush_interval_s,
        )
        context = multiprocessing.get_context("spawn")
        worker.process = context.Process(
            target=worker_main,
            args=(config,),
            name=f"combat-worker-{worker.slot}",
            daemon=True,
        )
        worker.process.start()

    # --- connections -------------------------------------------------------------------

    async def _on_connect(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        channel = ipc.IpcChannel(reader, writer)
        try:
            hello = await asyncio.wait_for(channel.recv(), 10)
        except Exception:
            channel.close()
            return
        if (
            not isinstance(hello, ipc.Hello)
            or not secrets.compare_digest(hello.boot_token, self._token)
            or not 0 <= hello.slot < len(self._workers)
        ):
            log.warning("rejected an IPC connection")
            channel.close()
            return
        worker = self._workers[hello.slot]
        worker.channel = channel
        worker.last_pong = self._clock.monotonic()
        worker.backoff_s = 1.0
        worker.ready.set()
        log.info("combat worker %d connected", worker.slot)
        try:
            while True:
                self._on_message(worker, await channel.recv())
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            if worker.channel is channel:
                self._lost(worker)

    def _on_message(self, worker: _Worker, msg: ipc.Message) -> None:
        if isinstance(msg, ipc.Reply):
            future = worker.pending.pop(msg.request_id, None)
            if future is not None and not future.done():
                future.set_result(msg)
        elif isinstance(msg, ipc.Pushed):
            self._push(msg.combat_id, msg.update)
        elif isinstance(msg, ipc.LoadReport):
            worker.load = msg.instances
        elif isinstance(msg, ipc.Pong):
            worker.last_pong = self._clock.monotonic()

    # --- requests ----------------------------------------------------------------------

    async def request(
        self, slot: int, make: Callable[[int], ipc._Msg]
    ) -> dict[str, Any] | None:
        """Send a request built by `make(request_id)`; return the reply payload or raise
        the worker's GameError (`combat.unavailable` if the worker is down)."""
        worker = self._workers[slot]
        if not worker.ready.is_set() or worker.channel is None:
            raise _unavailable()
        request_id = next(self._ids)
        future: asyncio.Future[ipc.Reply] = asyncio.get_running_loop().create_future()
        worker.pending[request_id] = future
        try:
            await worker.channel.send(make(request_id))
            reply = await asyncio.wait_for(future, REQUEST_TIMEOUT_S)
        except (ConnectionError, asyncio.TimeoutError) as exc:
            raise _unavailable() from exc
        finally:
            worker.pending.pop(request_id, None)
        if not reply.ok:
            raise GameError(reply.reason_key or "combat.internal", reply.status)
        return reply.payload

    # --- health ------------------------------------------------------------------------

    def _lost(self, worker: _Worker) -> None:
        worker.ready.clear()
        if worker.channel is not None:
            worker.channel.close()
        worker.channel = None
        for future in worker.pending.values():
            if not future.done():
                future.set_exception(_unavailable())
        worker.pending.clear()
        if not self._stopping and not worker.restarting:
            worker.restarting = True
            asyncio.get_running_loop().create_task(self._restart(worker))

    async def _restart(self, worker: _Worker) -> None:
        try:
            log.warning(
                "combat worker %d lost; restarting in %.0f s",
                worker.slot,
                worker.backoff_s,
            )
            if worker.process is not None and worker.process.is_alive():
                worker.process.kill()
                await asyncio.to_thread(worker.process.join, 5)
            await asyncio.sleep(worker.backoff_s)
            worker.backoff_s = min(MAX_BACKOFF_S, worker.backoff_s * 2)
            if not self._stopping:
                self._spawn(worker)
        finally:
            worker.restarting = False

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL_S)
            now = self._clock.monotonic()
            for worker in self._workers:
                if not worker.ready.is_set():
                    continue
                dead = worker.process is not None and not worker.process.is_alive()
                if dead or now - worker.last_pong > PING_TIMEOUT_S:
                    self._lost(worker)
                elif worker.channel is not None:
                    with contextlib.suppress(Exception):
                        await worker.channel.send(ipc.Ping())

    def kill_worker_for_tests(self, slot: int) -> None:
        process = self._workers[slot].process
        if process is not None:
            process.kill()
