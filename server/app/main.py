"""FastAPI entry point: `poetry run uvicorn app.main:app --app-dir server --reload`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import health, world
from app.config import REPO_ROOT, get_settings
from app.content.worldgen import load_worldgen_content
from app.persistence import worldgen_repo as repo
from app.persistence.db import dispose_engine, get_sessionmaker
from app.world_bootstrap import bootstrap_world

CLIENT_DIST = REPO_ROOT / "client" / "dist"


def create_app(
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    world_seed: int | None = None,
    client_dist: Path | None = CLIENT_DIST,
) -> FastAPI:
    """Build the app. Arguments override settings (tests pass their own DB and seed)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        content = load_worldgen_content()
        seed = world_seed
        if seed is None:
            seed = get_settings().require_world_seed()
        async with (sessionmaker or get_sessionmaker())() as session:
            generator = await bootstrap_world(session, seed, content)
            pins = await repo.load_pins(session)
        app.state.generator = generator
        app.state.galaxy = world.cache_galaxy(world.build_galaxy_view(generator, pins))
        try:
            yield
        finally:
            if sessionmaker is None:
                await dispose_engine()

    app = FastAPI(title="tg-stonks", lifespan=lifespan)
    app.include_router(health.router, prefix="/api")
    app.include_router(world.router, prefix="/api")
    # The built client (npm run build), same origin as /api. Mounted last so it never
    # shadows API routes. In dev, Vite serves the client and proxies /api here.
    if client_dist is not None and client_dist.is_dir():
        app.mount("/", StaticFiles(directory=client_dist, html=True), name="client")
    return app


app = create_app()
