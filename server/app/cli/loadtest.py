"""Load test: bot players fight hotseat demo combats over the real HTTP + WebSocket API.

Usage, from the repo root, with the server running (uvicorn spawns the combat workers):

    poetry run python server/app/cli/loadtest.py --bots 1000 --duration 120 --think-ms 3000

Each bot opens its demo combat (`POST /api/combats/demo`), connects to `/ws` (`hello`,
`combat.subscribe`) and plays random legal actions with a randomised think time, starting
a new demo whenever one ends. It measures intent → `combat.events` latency per action.

Sign-in is **not** part of the test: per-IP auth rate limits make 1,000 sign-ups from one
host impossible by design, and argon2 is not what's being measured. So the bots' users
(`lt_<n>`) are created directly in the DB from the same settings as the server
(`DATABASE_URL`), and access tokens are minted with the server's `AUTH_SECRET`. Everything
after that goes through the public API. Targets: docs/architecture.md "Budgets".
"""

import argparse
import asyncio
import dataclasses
import json
import multiprocessing
import os
import platform
import random
import statistics
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # allow running as a plain script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
import websockets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.passwords import Argon2Hasher
from app.auth.rules import normalize_username
from app.auth.tokens import TokenService
from app.config import get_settings
from app.persistence.db import create_engine
from app.persistence.models import User
from app.protocol import PROTOCOL_VERSION
from app.shared.clock import SystemClock

USER_PREFIX = "lt_"  # default; --user-prefix picks a fresh set of bots (and fights)
#: Mint a fresh token (and send `auth.refresh`) this long before the old one expires.
TOKEN_MARGIN_S = 120
CONNECT_TIMEOUT_S = 30
REPLY_TIMEOUT_S = 30


# --- setup: users and tokens ------------------------------------------------------------


async def seed_users(count: int, prefix: str = USER_PREFIX) -> list[int]:
    """Ensure users <prefix>0 … <prefix>{count-1} exist; return their ids in order."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    names = [f"{prefix}{i}" for i in range(count)]
    try:
        async with sessions() as session:
            rows = await session.execute(
                select(User.username_normalized, User.user_id).where(
                    User.username_normalized.in_([normalize_username(n) for n in names])
                )
            )
            existing = dict(rows.all())
            missing = [n for n in names if normalize_username(n) not in existing]
            if missing:
                # One real hash shared by all bots: nobody can sign in as them anyway.
                password_hash = await Argon2Hasher().hash(uuid.uuid4().hex)
                session.add_all(
                    User(
                        username=n,
                        username_normalized=normalize_username(n),
                        hashed_password=password_hash,
                        role="player",
                    )
                    for n in missing
                )
                await session.commit()
                rows = await session.execute(
                    select(User.username_normalized, User.user_id).where(
                        User.username_normalized.in_(
                            [normalize_username(n) for n in missing]
                        )
                    )
                )
                existing.update(rows.all())
        return [existing[normalize_username(n)] for n in names]
    finally:
        await engine.dispose()


def token_service() -> TokenService:
    settings = get_settings()
    return TokenService(
        settings.require_auth_secret(),
        ttl_s=settings.auth_access_ttl_s,
        clock=SystemClock(),
    )


# --- metrics ----------------------------------------------------------------------------


@dataclass
class Metrics:
    latencies_ms: list[float] = field(default_factory=list)
    #: wall-clock time of each accepted action (comparable across shard processes)
    action_times: list[float] = field(default_factory=list)
    #: size of each `combat.events` frame (bytes of JSON)
    push_bytes: list[int] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    bots_connected: int = 0
    combats_finished: int = 0

    def action(self, latency_ms: float) -> None:
        self.latencies_ms.append(latency_ms)
        self.action_times.append(time.time())

    def merge(self, other: "Metrics") -> None:
        self.latencies_ms += other.latencies_ms
        self.action_times += other.action_times
        self.push_bytes += other.push_bytes
        self.errors += other.errors
        self.bots_connected += other.bots_connected
        self.combats_finished += other.combats_finished


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p / 100 * len(ordered)))]


# --- one bot ----------------------------------------------------------------------------


def choose_intent(legal: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """A random legal intent, biased towards fighting so combats finish."""
    options: list[tuple[float, dict[str, Any]]] = []
    for a in legal["attacks"]:
        options.append(
            (4.0, {"type": "attack", "weapon": a["weapon"], "target": a["target"]})
        )
    for m in legal["moves"]:
        options.append(
            (1.0 / max(1, len(legal["moves"])) * 3, {"type": "move", "to": m["to"]})
        )
    for ab in legal["abilities"]:
        for uid in ab["target_units"]:
            options.append(
                (0.5, {"type": "ability", "ability": ab["ability"], "target_unit": uid})
            )
        for sq in ab["target_squares"][:5]:
            options.append(
                (
                    0.1,
                    {"type": "ability", "ability": ab["ability"], "target_square": sq},
                )
            )
    if legal["can_wait"]:
        options.append((0.2, {"type": "wait"}))
    options.append((1.0, {"type": "skip"}))
    weights = [w for w, _ in options]
    return rng.choices([o for _, o in options], weights=weights)[0]


class Bot:
    def __init__(
        self, index: int, user_id: int, args: argparse.Namespace, ctx: "Run"
    ) -> None:
        self.index = index
        self.user_id = user_id
        self.args = args
        self.ctx = ctx
        self.rng = random.Random(args.seed * 100_003 + index)
        self.next_id = 0
        self.combat_id = ""
        self.seq = 0
        self.legal: dict[str, Any] | None = None
        self.finished = False
        self.token_expires = 0.0

    def mint(self) -> str:
        token = self.ctx.tokens.issue(self.user_id, "player", f"loadtest-{self.index}")
        self.token_expires = time.time() + token.expires_in
        return token.token

    async def open_demo(self, http: httpx.AsyncClient, token: str) -> None:
        response = await http.post(
            "/api/combats/demo", headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        self.combat_id = response.json()["combat_id"]
        self.seq, self.legal, self.finished = 0, None, False

    async def request(
        self, ws: Any, type_: str, payload: dict[str, Any]
    ) -> float | None:
        """Send a request; process pushes until its ack/error. Returns the latency (ms) of
        the first `combat.events` that arrived, or None."""
        self.next_id += 1
        rid = f"b{self.next_id}"
        sent = time.perf_counter()
        await ws.send(json.dumps({"type": type_, "id": rid, "payload": payload}))
        first_events: float | None = None
        while True:
            raw = await asyncio.wait_for(ws.recv(), REPLY_TIMEOUT_S)
            message = json.loads(raw)
            kind = message["type"]
            if kind == "combat.events":
                self.ctx.metrics.push_bytes.append(len(raw))
            if kind in ("combat.snapshot", "combat.events"):
                body = message["payload"]
                if body["view"]["combat_id"] == self.combat_id:
                    self.seq = body["view"]["seq"]
                    self.legal = body["legal"]
                    self.finished = body["view"]["outcome"] is not None
                if kind == "combat.events" and first_events is None:
                    first_events = (time.perf_counter() - sent) * 1000
            elif message.get("id") == rid:
                if kind == "error":
                    raise RuntimeError(message["payload"]["reason_key"])
                return first_events

    async def run(self, http: httpx.AsyncClient, start: float, deadline: float) -> None:
        metrics = self.ctx.metrics
        starts_at = start + self.args.ramp * self.index / max(1, self.args.bots)
        await asyncio.sleep(max(0.0, starts_at - time.time()))
        token = self.mint()
        try:
            await self.open_demo(http, token)
            async with websockets.connect(
                self.ctx.ws_url, open_timeout=CONNECT_TIMEOUT_S, max_size=None
            ) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "hello",
                            "payload": {
                                "protocol_version": PROTOCOL_VERSION,
                                "access_token": token,
                            },
                        }
                    )
                )
                welcome = json.loads(await asyncio.wait_for(ws.recv(), REPLY_TIMEOUT_S))
                if welcome["type"] != "welcome":
                    raise RuntimeError(f"handshake: {welcome}")
                metrics.bots_connected += 1
                await self.request(
                    ws, "combat.subscribe", {"combat_id": self.combat_id}
                )
                while time.time() < deadline:
                    think = self.args.think_ms / 1000 * self.rng.uniform(0.5, 1.5)
                    await asyncio.sleep(think)
                    if time.time() > self.token_expires - TOKEN_MARGIN_S:
                        token = self.mint()
                        await self.request(ws, "auth.refresh", {"access_token": token})
                    if self.finished or self.legal is None:
                        if self.finished:
                            metrics.combats_finished += 1
                        await self.open_demo(http, token)
                        await self.request(
                            ws, "combat.subscribe", {"combat_id": self.combat_id}
                        )
                        continue
                    intent = choose_intent(self.legal, self.rng)
                    try:
                        latency = await self.request(
                            ws,
                            "combat.action",
                            {"combat_id": self.combat_id, "intent": intent},
                        )
                    except RuntimeError as error:
                        metrics.errors[f"action:{error}"] += 1
                        continue
                    if latency is not None:
                        metrics.action(latency)
        except (
            OSError,
            TimeoutError,
            websockets.WebSocketException,
            httpx.HTTPError,
        ) as error:
            metrics.errors[f"bot:{type(error).__name__}"] += 1
        except RuntimeError as error:
            metrics.errors[f"bot:{error}"] += 1


# --- run ----------------------------------------------------------------------------------


@dataclass
class Run:
    tokens: TokenService
    ws_url: str
    metrics: Metrics = field(default_factory=Metrics)


async def run_bots(
    args: argparse.Namespace, bots: list[tuple[int, int]], start: float
) -> Metrics:
    """Run `(index, user_id)` bots in this process from wall-clock `start`."""
    ctx = Run(
        token_service(), args.base_url.replace("http", "ws", 1).rstrip("/") + "/ws"
    )
    deadline = start + args.ramp + args.duration
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
    async with httpx.AsyncClient(
        base_url=args.base_url, limits=limits, timeout=60
    ) as http:
        await asyncio.gather(
            *(Bot(i, uid, args, ctx).run(http, start, deadline) for i, uid in bots)
        )
    return ctx.metrics


def shard_main(
    args: argparse.Namespace, bots: list[tuple[int, int]], start: float
) -> dict[str, Any]:
    """Entry point of one load-generator process (`--procs`). Returns plain data:
    classes defined in a spawned `__main__` don't unpickle in the parent."""
    metrics = asyncio.run(run_bots(args, bots, start))
    return {**dataclasses.asdict(metrics), "errors": dict(metrics.errors)}


async def main(args: argparse.Namespace) -> dict[str, Any]:
    print(f"seeding {args.bots} bot users…", flush=True)
    bots = list(enumerate(await seed_users(args.bots, args.user_prefix)))
    procs = max(1, min(args.procs, args.bots))
    print(
        f"running {args.bots} bots in {procs} process(es): "
        f"ramp {args.ramp}s, measure {args.duration}s…",
        flush=True,
    )
    if procs == 1:
        start = time.time()
        m = await run_bots(args, bots, start)
    else:
        start = time.time() + 3  # let the shard processes start up first
        shards = [bots[i::procs] for i in range(procs)]  # interleaved: even ramp
        loop = asyncio.get_running_loop()
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(procs, mp_context=context) as pool:
            parts = await asyncio.gather(
                *(
                    loop.run_in_executor(pool, shard_main, args, shard, start)
                    for shard in shards
                )
            )
        m = Metrics()
        for part in parts:
            m.merge(Metrics(**{**part, "errors": Counter(part["errors"])}))

    # Steady state only: the window after the ramp.
    window_start = start + args.ramp
    steady_lat = [
        lat
        for lat, t in zip(m.latencies_ms, m.action_times, strict=True)
        if t >= window_start
    ]
    report = {
        "bots": args.bots,
        "bots_connected": m.bots_connected,
        "loadgen_processes": procs,
        "think_ms": args.think_ms,
        "duration_s": args.duration,
        "actions_total": len(m.action_times),
        "actions_per_s": round(len(steady_lat) / args.duration, 1),
        "latency_ms": {
            "p50": round(percentile(steady_lat, 50), 1),
            "p95": round(percentile(steady_lat, 95), 1),
            "p99": round(percentile(steady_lat, 99), 1),
            "mean": round(statistics.fmean(steady_lat), 1) if steady_lat else None,
            "max": round(max(steady_lat), 1) if steady_lat else None,
        },
        "push_bytes": {
            "mean": round(statistics.fmean(m.push_bytes)) if m.push_bytes else None,
            "p95": percentile([float(b) for b in m.push_bytes], 95),
        },
        "combats_finished": m.combats_finished,
        "errors": dict(m.errors),
        "machine": {
            "cpu_count": os.cpu_count(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
    }
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--bots", type=int, default=100)
    parser.add_argument(
        "--duration", type=float, default=60, help="measured seconds after the ramp"
    )
    parser.add_argument(
        "--ramp", type=float, default=20, help="seconds over which bots start"
    )
    parser.add_argument(
        "--think-ms", type=float, default=3000, help="mean think time per action"
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--user-prefix",
        default=USER_PREFIX,
        help="bot usernames; a new prefix starts fresh fights (old ones resume)",
    )
    parser.add_argument(
        "--procs",
        type=int,
        default=1,
        help="load-generator processes (one Python loop saturates around 1k bots)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the report as JSON only"
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    result = asyncio.run(main(arguments))
    if arguments.json:
        print(json.dumps(result, indent=2))
    else:
        lat = result["latency_ms"]
        print(
            f"\nbots {result['bots_connected']}/{result['bots']} · "
            f"{result['actions_per_s']} actions/s · "
            f"intent→events p50 {lat['p50']} / p95 {lat['p95']} / p99 {lat['p99']} ms "
            f"(max {lat['max']}) · combats finished {result['combats_finished']}"
        )
        print(f"combat.events size: {result['push_bytes']} bytes")
        print(f"errors: {result['errors'] or 'none'}")
        print(f"machine: {result['machine']}")
