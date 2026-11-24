# Architecture

How the server runs the shared real-time world: the game loop, tick rates, where
authoritative state lives, how it is persisted, and how updates reach clients.
Target scale: 100–1000 concurrent players.

## Decided
- Single FastAPI process hosts HTTP API, WebSocket gateway and one asyncio game loop.
- Server-authoritative: clients send intents, server emits state deltas.
- Authoritative world state lives in memory; DB persistence is batched write-behind.
  Economic transactions commit atomically and immediately.
- Two tick rates: fast (movement, visibility) and slow (production, NPC economy).
- Interest management by sector (space) / planet (surface): clients receive only deltas
  for the area they are subscribed to.
- Combats run as separate instanced, turn-based state machines.
- **Entry point:** `server/app/main.py` (`create_app()`). Its lifespan:
  - loads the content;
  - runs `bootstrap_world`, which checks the world row and pins;
  - builds the cached static world views;
  - disposes the DB engine on shutdown.
- **Same origin:** FastAPI serves the API under `/api` and the built client
  (`client/dist`) at `/`. There is no CORS. In dev, Vite proxies `/api` and `/ws` to
  uvicorn (see [client](client.md)).
- Pure core (`sim/`, `world/`, `economy/`, `combat/`) has no I/O; shell layers
  (`api/`, `ws/`, `persistence/`) are thin.
- DB: Supabase Postgres, via SQLAlchemy 2.0 async (asyncpg driver) + Alembic.
  - Connection string comes from `DATABASE_URL` (env or repo-root `.env`); plain
    `postgresql://` URLs are rewritten to `postgresql+asyncpg://`.
  - Connect through Supabase's **Session pooler** (IPv4, port 5432): the direct
    `db.<ref>.supabase.co` host is IPv6-only. The transaction pooler (6543) would need
    asyncpg's prepared-statement cache disabled.
  - Engine/session factory: `server/app/persistence/db.py`; models in
    `server/app/persistence/models/`; migrations in `server/migrations/`.
  - Tests run against in-memory SQLite to keep models dialect-portable.

## Schema
- `users`: `user_id` BIGINT identity PK · `username` VARCHAR(32) unique · `hashed_password`
  VARCHAR(255). Only password hashes are stored. Telegram identity will link to this
  table later (see auth rule in CLAUDE.md).

## Open questions
- Exact tick rates (e.g. fast 10 Hz, slow 1/min?).
- Write-behind flush interval and crash-recovery guarantees (what can be lost on crash?).
- Sector size and how sector handoff works for moving ships.
- When to split into multiple processes/workers, and how state is sharded then.
- Hosting/deployment target.
