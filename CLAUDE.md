# CLAUDE.md

Mobile-first browser MMO: 2D pixel-art space exploration. Procedurally generated galaxy,
production-chain economy, ship travel + planet expeditions, turn-based ship combat and
turn-based squad combat (per-unit Speed initiative HOMM-style, multi-model 40k-style units,
abilities as event-hooked Python functions). Runs as a mobile web app; Telegram Mini App
support comes after launch (no Telegram code until then).

Design lives in `docs/` — read the relevant doc before touching a system:
[architecture](docs/architecture.md) · [protocol](docs/protocol.md) ·
[world-gen](docs/world-gen.md) · [economy](docs/economy.md) ·
[combat-space](docs/combat-space.md) · [combat-ground](docs/combat-ground.md) ·
[content-pipeline](docs/content-pipeline.md) · [client](docs/client.md) ·
[lobby-rooms](docs/lobby-rooms.md)

## Stack
- Server: Python 3.12, FastAPI, WebSockets, SQLAlchemy 2.0 (async) + Alembic, Pydantic v2
- Auth: joserfc (Authlib project; JWT), argon2-cffi (passwords); Authlib OAuth client reserved
  for social login later
- Processes: one gateway (uvicorn, `--workers 1`) + combat worker processes it spawns
  (see [architecture](docs/architecture.md))
- DB: Supabase Postgres (asyncpg driver); SQLite (aiosqlite) for tests.
- Client: TypeScript (strict), Phaser 4 (scenes), Preact + @preact/signals (DOM overlays), Vite
- Tooling: Poetry, black, pytest · npm, vitest

## Commands
Server (from the repo root — `pyproject.toml` and `alembic.ini` live there, code in `server/`):
- `poetry install` · `poetry run uvicorn app.main:app --app-dir server --reload`
- `poetry run pytest` (single: `poetry run pytest server/tests/path::test_name`)
- `poetry run black server`
- `poetry run alembic revision --autogenerate -m "msg"` · `poetry run alembic upgrade head`
- `poetry run python server/app/cli/init_world.py` — create/check the world row (idempotent)
- `poetry run python server/app/cli/snapshot_world.py` — dump the whole generated galaxy
  into debug `gen_*` tables for browsing (never read by the game; safe to drop)
- `poetry run python server/app/cli/bench_combat.py` — engine benchmark (per-turn p50/p95/p99)
- `poetry run python server/app/cli/loadtest.py --bots 1000 --duration 120 --think-ms 3000`
  — bots play demo combats over HTTP + `/ws` against a running server (seeds `lt_*` users
  in `DATABASE_URL` and mints tokens with `AUTH_SECRET`: point both at a scratch DB, never
  the live one)
- `poetry run pytest -m "not slow"` skips the real-process worker tests; `-m perf` runs the
  engine perf guard only
- Config in repo-root `.env`: `DATABASE_URL` (Supabase via Session pooler), `WORLD_SEED`
  (never change it once the world exists), `AUTH_SECRET` (≥ 32 bytes; **the server won't
  start without it**), `COMBAT_WORKERS` (default: CPU cores − 1) — full list in
  [architecture](docs/architecture.md#configuration-and-secrets).
- uvicorn spawns the combat workers itself (also with `--reload`); their logs are prefixed
  `[worker N]`. Env vars override `.env` (e.g. a scratch `DATABASE_URL`).
- Never run uvicorn with `--workers > 1`: the gateway must hold every connection.

Client (from `client/`; run uvicorn alongside — Vite proxies `/api` and `/ws` to :8000):
- `npm i` · `npm run dev` · `npm run build` · `npm test` · `npm run typecheck`
- `npm run gen:protocol` — regenerate TS protocol types from server Pydantic schemas
  (`-- --check` fails if the committed file is stale)
- `npm run build` output (`client/dist`) is served by FastAPI at `/` (same origin).
- On Windows run npm/vitest from PowerShell/cmd, not Git Bash `/d/...` paths (vitest breaks).

## Layout
```
server/app/
  api/          HTTP routes (auth, account, static data) — thin
  ws/           WebSocket gateway: auth, decode intents, push deltas — thin
  auth/         passwords (argon2id), JWT access tokens, refresh tokens, dependencies
  services/     gateway-side orchestration (combat router, backends)
  workers/      combat worker processes: IPC, supervisor, combat host/instances
  sim/          game loop, world state, systems (movement, production, NPC AI) — NO I/O
  world/        procedural generation (pure, seeded)
  economy/      recipes, markets, ledger
  combat/       space/ and ground/ rule engines 
  persistence/  SQLAlchemy models, repositories, write-behind flusher
  protocol/     Pydantic message schemas (source of truth for client types)
server/migrations/  Alembic
server/tests/       mirrors server/app/
client/src/   scenes/ (Phaser) · combat/ (pure combat UI logic) · net/ (http, ws) · ui/ · state/ · i18n/ · protocol/ (generated)
content/      TOML game data: items, recipes, hulls, modules, unit types, factions
locales/      en.json, ua.json
docs/         design docs
```

## Architecture rules (non-negotiable)
1. **Server-authoritative.** Client sends *intents* (move_to, place_order, activate_unit);
   server validates and emits state deltas. Never trust client positions, quantities or results.
2. **Pure core, thin shell.** `sim/`, `world/`, `economy/`, `combat/` do no DB, network or
   clock access. Time, RNG and inputs are passed in — everything is unit-testable and replayable.
3. **Determinism.** All randomness comes from explicit `random.Random(seed)` instances — never
   the global `random` module. Combat rolls are logged so fights can be replayed.
4. **Procgen = seed + deltas.** Generated content is a function of
   `(world_seed, coords, GENERATOR_VERSION)`. Persist only player-caused changes, never
   generated data. Changing a generator's output requires bumping its version and a
   migration note in `docs/world-gen.md`.
5. **Processes and loops.** One gateway process holds every client connection, auth and
   routing — it never runs game rules or CPU-heavy work on its event loop (argon2 goes to a
   thread pool). Game state lives in worker processes (combat workers now; world-sim
   workers later with fast/slow ticks), each with its own asyncio loop. Authoritative state
   is in memory; persistence is batched write-behind — never write to the DB per player
   action in the hot path. Exception: account and economic transactions commit atomically.
6. **Interest management.** Clients subscribe to their current sector/planet; send only
   deltas for that area. Never broadcast world-wide state.
7. **Combat is instanced.** A combat is a self-contained turn-based state machine spawned from
   the world sim; it validates each action against the rules engine and resolves server-side.
8. **Economy integrity.** Money and quantities are `int` (minor units), never float.
   Every currency/item movement goes through the ledger service. NPC actors use the same
   market API as players — no hidden side doors.
9. **Data-driven content.** Items, recipes, ships, units live in `content/*.toml`, validated
   by Pydantic at startup. No hard-coded balance numbers in logic.
10. **DB portability.** No SQLite-only SQL, no dialect-specific raw queries; use SQLAlchemy
    Core/ORM. Alembic runs with `render_as_batch=True`. DB chosen via `DATABASE_URL`.
    SQLite runs in WAL mode. No Supabase client SDK in game code — Postgres via SQLAlchemy only.
11. **Auth.** Own username + password login (argon2id). The server issues short-lived JWT
    access tokens (memory only on the client, Bearer / WS `hello`) and a rotating refresh
    token in an httpOnly `__Host-` cookie with reuse detection. Telegram sign-in comes after
    launch; new sign-in methods plug in via an `identities` table (see
    [architecture](docs/architecture.md#authentication)).

## Protocol
- Pydantic models in `server/app/protocol/` are the single source of truth; TS types are
  generated (`npm run gen:protocol`). Never hand-edit `client/src/protocol/`.
- Any message change: update schema, regenerate, bump `PROTOCOL_VERSION`, update `docs/protocol.md`.

## Client rules
- Mobile first: touch input, portrait-first layouts, tap targets ≥ 44px, test at 360×640.
- Pixel art: Phaser `pixelArt: true`, `roundPixels`, integer scaling; sprites in texture atlases.
- Client renders and interpolates server state; it may predict movement visually but never
  decides outcomes. Menus/complex panels may be DOM overlays; maps and combat are Phaser scenes.
- All player-facing text via i18n keys (`t('market.buy')`); content TOML uses name keys, not
  literal names. Add every key to both `en.json` and `ua.json`.

## Conventions
- Code, identifiers and comments in English, generate content only for english.
- Python: type hints on all public functions; Pydantic for I/O schemas, dataclasses for sim state;
  black formatting.
- TS: `strict: true`, no `any` in `net/` or `protocol/`.
- New system or rule change → update the matching `docs/*.md` in the same change.
- Tests are required for rules engines (combat, economy, procgen determinism).
