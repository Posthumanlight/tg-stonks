"""FastAPI entry point (the gateway): `poetry run uvicorn app.main:app --app-dir server`.

This is the composition root: every service is built and wired here, so the rest of
the code receives its dependencies instead of constructing them.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import auth, combats, health, rooms, world
from app.combat.ground.ruleset import CombatRuleset, load_ruleset
from app.combat.ground.deployment import load_battle_map
from app.persistence.combat_repo import CombatStore
from app.lobby.service import SWEEP_INTERVAL_S as ROOM_SWEEP_INTERVAL_S
from app.lobby.service import RoomService
from app.lobby.store import MemoryRoomStore
from app.services.combat_backend import CombatBackend, ProcessBackend
from app.services.combat_router import CombatRouter
from app.services.custom_battles import CustomBattles
from app.workers.supervisor import Supervisor, SupervisorConfig
from app.auth.cookies import CookiePolicy
from app.auth.dependencies import AuthComponents, AuthLimits
from app.auth.passwords import Argon2Hasher, PasswordHasher
from app.auth.refresh import RefreshService
from app.auth.service import AuthService
from app.auth.tokens import TokenService
from app.config import REPO_ROOT, Settings, get_settings
from app.content.worldgen import load_worldgen_content
from app.persistence import worldgen_repo as repo
from app.persistence.auth_repo import RefreshStore, UserStore
from app.persistence.db import dispose_engine, get_sessionmaker
from app.shared.clock import Clock, SystemClock
from app.shared.errors import install_error_handlers
from app.world_bootstrap import bootstrap_world
from app.ws import gateway as ws_gateway

CLIENT_DIST = REPO_ROOT / "client" / "dist"
REFRESH_CLEANUP_INTERVAL_S = 24 * 3600

log = logging.getLogger(__name__)


def build_auth(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    hasher: PasswordHasher,
) -> AuthComponents:
    tokens = TokenService(
        settings.require_auth_secret(),
        previous_secret=settings.previous_auth_secret(),
        ttl_s=settings.auth_access_ttl_s,
        clock=clock,
    )
    refresh = RefreshService(
        RefreshStore(sessions), ttl_s=settings.auth_refresh_ttl_s, clock=clock
    )
    return AuthComponents(
        service=AuthService(UserStore(sessions), refresh, tokens, hasher),
        tokens=tokens,
        limits=AuthLimits.defaults(clock),
        cookie=CookiePolicy(
            secure=settings.auth_cookie_secure, max_age=settings.auth_refresh_ttl_s
        ),
    )


BackendFactory = Callable[[Settings, CombatRuleset, CombatStore, Clock], CombatBackend]


def process_backend(
    settings: Settings, ruleset: CombatRuleset, store: CombatStore, clock: Clock
) -> CombatBackend:
    """Production: combats in worker processes (docs/architecture.md)."""
    return ProcessBackend(
        Supervisor(
            SupervisorConfig(
                workers=settings.combat_worker_count,
                database_url=settings.database_url,
                pool_size=settings.db_pool_worker,
                idle_timeout_s=settings.combat_idle_timeout_s,
                flush_interval_s=settings.combat_flush_interval_s,
            ),
            clock,
        )
    )


async def _cleanup_refresh_tokens(auth: AuthComponents) -> None:
    while True:
        await asyncio.sleep(REFRESH_CLEANUP_INTERVAL_S)
        try:
            removed = await auth.service.refresh_tokens.cleanup()
            log.info("removed %d expired refresh tokens", removed)
        except Exception:  # keep the loop alive; the next run retries
            log.exception("refresh-token cleanup failed")


async def _every(interval_s: float, job: Callable[[], Awaitable[None]]) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            await job()
        except Exception:  # keep the loop alive; the next run retries
            log.exception("periodic job failed")


def create_app(
    *,
    settings: Settings | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    world_seed: int | None = None,
    client_dist: Path | None = CLIENT_DIST,
    clock: Clock | None = None,
    password_hasher: PasswordHasher | None = None,
    combat_backend: BackendFactory | None = None,
) -> FastAPI:
    """Build the gateway app. Arguments override settings and defaults (tests inject
    their own DB, seed, clock, cheap hasher and in-process combat backend)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings or get_settings()
        sessions = sessionmaker or get_sessionmaker()
        seed = world_seed if world_seed is not None else config.require_world_seed()
        time = clock or SystemClock()
        app.state.clock = time

        app.state.auth = build_auth(
            config, sessions, time, password_hasher or Argon2Hasher()
        )
        async with sessions() as session:
            generator = await bootstrap_world(session, seed, load_worldgen_content())
            pins = await repo.load_pins(session)
        app.state.generator = generator
        app.state.galaxy = world.cache_galaxy(world.build_galaxy_view(generator, pins))

        ruleset = load_ruleset()
        # Content checks (the default armies, too) fail before any worker starts.
        app.state.custom_battles = CustomBattles(ruleset, load_battle_map(ruleset))
        store = CombatStore(sessions)
        backend = (combat_backend or process_backend)(config, ruleset, store, time)
        await store.fold_slots(backend.slots)
        await backend.start()
        app.state.combat_store = store
        app.state.combat_router = CombatRouter(backend, store)
        users = UserStore(sessions)

        async def user_name(user_id: int) -> str:
            user = await users.get(user_id)
            return user.username if user is not None else f"#{user_id}"

        app.state.rooms = RoomService(
            store=MemoryRoomStore(),
            ruleset=ruleset,
            battle_map=app.state.custom_battles.room_map,
            combats=app.state.combat_router,
            user_name=user_name,
            clock=time,
        )

        app.state.ws_watchdog = ws_gateway.Watchdog(time)
        watchdog = asyncio.create_task(app.state.ws_watchdog.run())
        cleanup = asyncio.create_task(_cleanup_refresh_tokens(app.state.auth))
        room_sweeper = asyncio.create_task(
            _every(ROOM_SWEEP_INTERVAL_S, app.state.rooms.sweep)
        )
        try:
            yield
        finally:
            for task in (cleanup, watchdog, room_sweeper):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await backend.stop()
            if sessionmaker is None:
                await dispose_engine()

    app = FastAPI(title="tg-stonks", lifespan=lifespan)
    install_error_handlers(app)
    for module in (health, auth, world, combats, rooms):
        app.include_router(module.router, prefix="/api")
    app.include_router(ws_gateway.router)  # /ws
    # The built client (npm run build), same origin as /api. Mounted last so it never
    # shadows API routes. In dev, Vite serves the client and proxies /api here.
    if client_dist is not None and client_dist.is_dir():
        app.mount("/", StaticFiles(directory=client_dist, html=True), name="client")
    return app


app = create_app()
