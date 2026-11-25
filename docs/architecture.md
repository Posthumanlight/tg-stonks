# Architecture

How the server runs: processes, authentication, the lobby, combat instances over
WebSockets, persistence, and how it scales to the target of **1,000 concurrent players**.
This is the implementation spec for the server shell and core infrastructure. Game rules
live in their own docs ([world-gen](world-gen.md), [combat-ground](combat-ground.md), …),
and the wire format in [protocol](protocol.md).

---

## Decided

### Principles
- **Server-authoritative** (CLAUDE.md rule 1). Clients send intents, and the server
  validates them, resolves them and pushes the results.
- **Pure core, thin shell** (rule 2). `world/`, `combat/`, and later `sim/` and
  `economy/`, have no I/O, clock or global RNG. The shell layers (`api/`, `ws/`, `auth/`,
  `services/`, `workers/`, `persistence/`) only translate and route.
- **Multi-process from day one.**
  - One **gateway** process faces every client.
  - **Combat worker processes** own the combat instances and do the CPU work.
  - The reason is in [Scalability](#scalability-and-capacity-model): one Python process
    uses one core, and the combat engine alone would saturate it at the target load.
- **Same origin.** The gateway serves the API under `/api`, the WebSocket at `/ws` and
  the built client at `/`. There is no CORS. In dev, Vite proxies `/api` and `/ws` to
  uvicorn (see [client](client.md)).
- **Auth.** Users log in with username and password. The server issues JWT access tokens
  (with `joserfc`, the Authlib project's JOSE library) and a rotating refresh token in an
  httpOnly cookie.
  - Telegram sign-in is **dropped for now**.
  - Social login (Authlib's OAuth client) is designed in but not built.
- **Persistence.** The Supabase Postgres connection is unchanged (see
  [Database](#database)). Writes from gameplay are batched (write-behind, rule 5).
  Account and economic writes commit immediately.
- **Combats survive restarts by replay.** The engine is deterministic, so a persisted
  combat record (setup, seed, content hash, rules version, actions) rebuilds any fight
  exactly.

---

## Process topology

```
             ┌────────────── gateway (1 process, uvicorn workers=1) ──────────────┐
 clients ──► │ HTTP API · auth · lobby · static client · WS gateway (all sockets) │
 (HTTPS,     │ CombatRouter: combat_id → worker · subscriptions combat_id → conns │
  WSS)       └───────▲───────────────┬───────────────────────────────▲────────────┘
                     │ framed IPC (localhost TCP / Unix socket)       │ asyncpg pool
             ┌───────┴──────┐ ┌──────┴───────┐     ┌──────────────┐ │
             │ combat wkr 0 │ │ combat wkr 1 │ ... │ combat wkr N │─┴─► Postgres
             │ instances,   │ │              │     │ own small    │     (Supabase)
             │ engine, RNG, │ │              │     │ DB pool      │
             │ write-behind │ │              │     │              │
             └──────────────┘ └──────────────┘     └──────────────┘
```

| Process | Count | Owns | Never does |
|---|---|---|---|
| **Gateway** | exactly 1 | HTTP API, auth, lobby, static files, every WebSocket, subscriptions, rate limits, worker supervision, the cached static world views | run the combat engine; hash passwords on the event loop |
| **Combat worker** | `COMBAT_WORKERS` (default: CPU cores − 1, minimum 1) | its combat instances: state, RNG, event log, seat checks, timers, write-behind of their actions, recovery by replay | talk to clients directly |
| **World sim** (future) | by sector | the real-time world (ships, production) | — it follows the same pattern; see Open questions |

- **One gateway, one uvicorn worker.** All connections and subscriptions must live in
  one place, so the gateway is **never** started with `--workers > 1`. Combat workers are
  the server's own child processes, not uvicorn workers.
- **Workers are spawned by the gateway**: `multiprocessing` with the spawn context, which
  works the same on Windows dev machines and Linux. The gateway supervises them and
  restarts any that crash (see [Failure modes](#failure-modes)).

### Request paths
- **HTTP:** client → `api/` route → service → `persistence/` repository → Postgres.
- **Combat intent:**
  1. The client sends `combat.action` over `/ws`.
  2. The gateway authenticates it, rate-limits it and routes it to the owning worker.
  3. In the worker, `CombatInstance` checks the seat and runs the pure engine
     `apply_action`.
  4. The worker sends a reply and pushes events back to the gateway.
  5. The gateway fans the events out to the combat's subscribers.

---

## Module layout

```
server/app/
  main.py            gateway create_app(): lifespan = load content + ruleset, bootstrap
                     world, start the worker supervisor; dispose the DB engine on shutdown
  config.py          settings (DB, world seed, auth, workers, pools)
  auth/              passwords.py   argon2id hash/verify (run in a thread pool)
                     tokens.py      issue/verify JWT access tokens (joserfc)
                     refresh.py     refresh-token issue/rotate/revoke (reuse detection)
                     dependencies.py current_user, require_role (FastAPI)
                     ratelimit.py   in-memory token buckets
  api/               health.py, world.py, auth.py, combats.py — thin routes
  ws/                gateway.py     /ws endpoint: handshake, read loop, close codes
                     connection.py  outbound queue, heartbeat, per-connection rate limit
                     router.py      message type → handler
  services/          combat_router.py  gateway side: placement, forwarding, fan-out
                     combat_backend.py CombatBackend interface: ProcessBackend (production),
                                       InProcessBackend (unit tests only)
  workers/           combat_worker.py  worker process entry point (own event loop)
                     combat_host.py    the instances living in one worker
                     combat_instance.py wraps the pure engine for one combat
                     ipc.py            framing + internal message models
                     supervisor.py     spawn, heartbeat, restart with backoff, drain
  protocol/          client-facing Pydantic models (source of TS types): + auth.py,
                     ws.py (envelope + messages), combat.py (views)
  persistence/       models (+ refresh_tokens, combats, combat_actions), repositories,
                     flusher.py (write-behind)
  world/, combat/    pure core (existing)
```

---

## Configuration and secrets

All settings come from the environment or the repo-root `.env` (`server/app/config.py`).

| Key | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | Supabase Session pooler URL (see [Database](#database)) |
| `WORLD_SEED` | — | the persistent galaxy (see [world-gen](world-gen.md)) |
| `AUTH_SECRET` | — | HS256 signing key, ≥ 32 random bytes. Required |
| `AUTH_SECRET_PREVIOUS` | empty | old key still accepted for verification during rotation |
| `AUTH_ACCESS_TTL_S` | 900 | access-token lifetime (15 min) |
| `AUTH_REFRESH_TTL_S` | 2592000 | refresh-token lifetime (30 days) |
| `AUTH_COOKIE_SECURE` | true | `Secure` cookie flag; only `false` for plain-HTTP local dev |
| `COMBAT_WORKERS` | cores − 1 | number of combat worker processes |
| `DB_POOL_GATEWAY` | 5 | gateway connection pool size |
| `DB_POOL_WORKER` | 2 | per-worker pool size |

- **Connection budget:** `DB_POOL_GATEWAY + COMBAT_WORKERS × DB_POOL_WORKER` must stay
  below the Supabase pooler's client limit for the plan in use. Check it before raising
  `COMBAT_WORKERS`.
- **Secrets** (`DATABASE_URL`, `AUTH_SECRET*`) are never logged, echoed in errors, or
  sent to the client.
- **Key rotation:** tokens carry a `kid` header.
  1. Set the new key as `AUTH_SECRET` and the old one as `AUTH_SECRET_PREVIOUS`.
  2. Wait one access-token lifetime.
  3. Remove the old key.

---

## Authentication

**Libraries:**
- `joserfc` (the Authlib project's JOSE library; Authlib's own `authlib.jose` is
  deprecated in its favour) for JWT;
- `argon2-cffi` for password hashing;
- `authlib` (Starlette OAuth client) is reserved for social login later.

### Accounts (v1: username + password)
- **Usernames:** 3–32 characters of `[A-Za-z0-9_]`. They are unique
  **case-insensitively**, through a `username_normalized` column (lower-case, unique
  index). The display form keeps the user's casing.
- **Passwords:** 10–128 characters, with no composition rules (NIST 800-63B). The upper
  bound caps hashing cost.
- **Hashing:** argon2id with parameters from settings.
  - Hashing and verifying run in a **thread pool** (`anyio.to_thread.run_sync`).
    `argon2-cffi` releases the GIL, so a burst of logins never stalls the event loop.
  - On successful login, a hash made with outdated parameters is re-hashed
    (`check_needs_rehash`).

### Endpoints
| Method and path | Body / result | Notes |
|---|---|---|
| `POST /api/auth/register` | `{username, password}` → `201 {user}` | validates the rules above; `409` if the name is taken. Doesn't log in |
| `POST /api/auth/login` | `{username, password}` → `{access_token, expires_in, user}` + refresh cookie | constant-time: an unknown user is verified against a dummy hash; failures return a generic `401 auth.invalid_credentials` |
| `POST /api/auth/refresh` | cookie → `{access_token, expires_in, user}` + rotated cookie | `401` if missing, expired or revoked; requires a same-origin `Origin` header |
| `POST /api/auth/logout` | cookie → `204` | revokes the current refresh family; clears the cookie |
| `POST /api/auth/logout-all` | Bearer → `204` | revokes every refresh family of the user |
| `GET /api/auth/me` | Bearer → `{user}` | the current user (id, username, role) |

### Access token (JWT)
- **Algorithm:** HS256 only, so the verifier pins an algorithm allow-list. The `kid`
  header selects the key.
- **Claims:**
  - `iss` = `tg-stonks`, `aud` = `tg-stonks-client`;
  - `sub` = user id (string);
  - `iat`, `exp` (now + `AUTH_ACCESS_TTL_S`);
  - `jti` (random);
  - `role`;
  - `sid` = the refresh-token family id, so a logout can be tied to tokens.
- **Verification:** joserfc decode plus a claims registry. `exp`, `iss`, `aud` and `sub`
  are required, with a 30 s leeway.
- **Transport:**
  - HTTP: `Authorization: Bearer <token>`;
  - WebSocket: the `hello` message (see [WebSocket gateway](#websocket-gateway)), never
    the URL. URLs end up in logs.
- **Client storage: memory only.** No `localStorage`, so XSS can't read a long-lived
  credential. A page reload gets a new token through refresh.

### Refresh tokens
- **Value:** an opaque random value (32 bytes, base64url). The DB stores only its
  **SHA-256 hash**.
- **Cookie:** `__Host-refresh=<value>`; `HttpOnly`; `Secure`; `SameSite=Strict`;
  `Path=/`; `Max-Age` = the refresh TTL. The `__Host-` prefix forbids a `Domain`
  attribute, so the cookie can't leak to subdomains.
- **Rotation:** every refresh revokes the presented token and issues a new one in the
  same **family**, all in one transaction.
- **Reuse detection:** presenting a token that was already rotated means it was copied.
  The **whole family is revoked**, and the user must log in again on that device.
  - **Exception: two tabs refreshing at once.** Within 10 s of a rotation, presenting the
    old token gets `409 auth.refresh_race`, and the family survives.
  - The losing tab retries once after a short delay. The browser's cookie jar already
    holds the winner's new token.
- **CSRF:** the cookie is `SameSite=Strict` and only the auth endpoints read it. The
  refresh endpoint also rejects requests whose `Origin` isn't our host. API calls use the
  Bearer header, which a cross-site page can't attach.
- **Table `refresh_tokens`:**

  | Column | Type | Notes |
  |---|---|---|
  | `token_id` | BIGINT identity PK | |
  | `user_id` | BIGINT FK → users | indexed |
  | `family_id` | UUID | one per login (device session) |
  | `token_hash` | CHAR(64) | unique index |
  | `created_at`, `expires_at` | timestamptz | |
  | `revoked_at` | timestamptz null | |
  | `replaced_by_id` | BIGINT null | the token this one was rotated into |

  Expired rows are deleted by a daily cleanup task in the gateway.
- **Plain-HTTP local dev:** with `AUTH_COOKIE_SECURE=false` the cookie is named
  `refresh`, because browsers reject a `__Host-` cookie without `Secure`.

### Client flow
1. On load, the client calls `POST /api/auth/refresh`.
   - Success: it has an access token and the user, and shows the lobby.
   - Failure: it shows login/register.
   - `409 auth.refresh_race`: it retries once after a short delay.
2. The client refreshes about a minute before `expires_in` runs out. On any `401` from
   the API, it refreshes once and retries once.
3. Logout calls `/api/auth/logout` and drops the in-memory token.

### Rate limits
In-memory token buckets in the gateway. They're correct because the gateway is a single
process.

| Bucket | Limit | On excess |
|---|---|---|
| login per IP | 10 / min | `429` + `Retry-After` |
| login per username | 5 / min | `429` |
| register per IP | 5 / hour | `429` |
| refresh per IP | 10 / min | `429` |

### Later: more sign-in methods (designed, not built)
- **Table:** `identities(user_id, provider, subject, data, created_at)`, with
  `(provider, subject)` unique. Password login stays on `users`.
- **Social login:** Authlib's Starlette OAuth client for Google or Discord. A successful
  callback finds or creates the user through `identities`, then issues the same
  access/refresh pair.
- **Telegram:** initData HMAC verification could return as one more provider (it was
  dropped for now).

---

## Authorization
- **Roles:** a `users.role` column, `player` (default) or `admin`.
- **FastAPI dependencies:**
  - `current_user` verifies the Bearer token and returns a `Principal` (user id, role,
    session) from its claims, **with no DB lookup**, so authenticated requests stay
    cheap. A role change therefore takes effect at the next refresh (≤ 15 min);
  - `require_role("admin")` restricts admin routes.
- **Resource rules live with the resource, never in the client:**
  - **Combat seats.** The worker that owns a combat checks every intent against its
    **seat map** (side → user). The gateway only forwards `user_id`.
    - Hotseat: the owner holds every side.
    - PvP (later): one side per player.
  - Subscribing to a combat requires a seat. Spectators come later.
- **Endpoint access:**

  | Path | Access |
  |---|---|
  | `/api/health`, static client | public |
  | `/api/auth/register`, `/login`, `/refresh`, `/logout` | public (rate-limited) |
  | `/api/auth/me`, `/logout-all`, `/api/world/*`, `/api/combats/*`, `/ws` | authenticated |

---

## Lobby

The first screen after login. It is client-side for v1; `/api/auth/me` supplies the
user.

- **Client screens:** a `screen` signal drives `login → lobby → galaxy | combat`.
  Menus are Preact DOM overlays (see [client](client.md)).
- **Lobby contents (v1):**
  - **"Galaxy chart"** opens the existing `GalaxyScene` with `GET /api/world/galaxy`.
  - **"Combat demo"** is a **placeholder**: a disabled button marked "coming soon" until
    the combat gateway ships.
  - The username and a logout button.
- **Later (spec'd here):**
  - **"Combat demo"** calls `POST /api/combats/demo` and opens the combat scene. That
    endpoint creates the user's hotseat instance of the fixed demo battle, or returns the
    existing one: **one active hotseat per user**.
  - `GET /api/combats` lists the user's active combats, so the lobby can offer
    "Resume".

---

## Combat instances

A combat is a self-contained, turn-based state machine (rule 7). The pure engine
(`server/app/combat/ground/engine.py`) is wrapped by a `CombatInstance` living in one
combat worker.

### v1: hotseat demo
- **Hotseat:** one user controls **every** side on one device. It is a sandbox for the
  rules, with no AI and no matchmaking.
- **The battle** is **one fixed demo battle**, defined as data in
  `content/combat/demo.toml` (rule 9): the board size, terrain rows (ASCII with a
  legend), and both armies as `UnitSetup` entries. It is validated at startup like other
  content. Changing the demo is a content change.

### Gateway side: `CombatRouter`
- **Placement:** a new combat goes to the **least-loaded** worker. Load is the
  instance count, reported by each worker in `load_report` (every 5 s).
  - A placement counts **as soon as it's decided** (`CombatBackend.loads()` contract);
    the next report replaces the estimate. Without this, every combat created between
    two reports went to the same worker (the load test saw 160–184 fights on six
    workers and none on three).
  - The mapping `combat_id → worker_slot` is kept in gateway memory.
  - It is also written to `combats.worker_slot`, so recovery knows where each combat
    lives.
- **Forwarding:** each intent goes to its worker as `{user_id, request_id, combat_id,
  action}`.
- **Fan-out:** the router keeps the subscriptions (`combat_id → connections`). Each
  `pushed` message from a worker is sent to every subscribed connection.
  - The worker serializes each `CombatUpdate` **once** (`model_dump_json`). `pushed`
    carries it as JSON text, and the gateway splices that text into the WebSocket frame
    without parsing it. Parsing it into dicts and re-encoding it cost the gateway a
    measurable share of its single core. Each `reply`
  goes only to the connection that sent the request.

### Worker side: `CombatHost` and `CombatInstance`
A `CombatInstance` holds:
- **Engine state:** the ruleset reference, `CombatState`, and its own
  `random.Random(seed)`.
- **The record:** setup, seed, content hash, rules version, actions. This is the
  engine's `CombatRecord`.
- **An event log** with a sequence number (`seq`) per event, kept in memory for
  resyncs.
- **Access:** the seat map.
- **No lock.** An intent is handled synchronously, with no `await` between reading and
  writing the state, so two intents can never interleave on the worker's event loop.
- **Status:** `active | finished | abandoned | aborted`.

`CombatInstance` (`workers/combat_instance.py`) has no I/O. `CombatHost`
(`workers/combat_host.py`) does the persistence and publishing. Updates leave through
an injected `publish` callback: IPC in a worker process, a direct call in
`InProcessBackend`.

**Intent flow:**
1. **Gateway:** authenticate the connection, rate-limit it, look up the worker, forward
   the intent.
2. **Worker:** check the seat. The user must hold the side of the active unit, or get
   `error {combat.not_your_turn}`.
3. **Worker:** translate the intent into an engine action.
   - `move {to}` names only a destination. The worker takes the path from the legal
     moves it showed the client, so paths are never sent over the wire.
   - Then it calls `engine.apply_action(ruleset, state, action, rng)`. That call is pure,
     synchronous and fast (see [Scalability](#scalability-and-capacity-model)).
4. **Worker:** append the action to the record and the events to the log with new seqs,
   then queue the action for write-behind.
5. **Worker → gateway:**
   - `pushed {combat_id, update}`, where `update` is a `CombatUpdate`: the new events,
     the post-action `CombatView` and the next `CombatLegal`;
   - `reply {request_id, ok}` for the sender.
6. **Gateway:** fan out the push to the subscribers.

**On `IllegalAction`:** the worker replies `error {request_id, reason_key}` and pushes
nothing. The engine guarantees the state and RNG are untouched, so the recorded action
list stays replayable.

**Seeds:** a combat's seed is drawn with `secrets.randbits(63)` in the worker shell at
creation and stored in the record. The pure engine never draws its own randomness.

### Views (client-facing protocol models)
All of these are in `server/app/protocol/combat.py`, with pure converters from engine
state.
- **`CombatView`:** combat id, units (type, side, origin, groups' alive counts, wounded
  model, statuses, reactions), overlays, round, active unit and its budget, queues,
  outcome, and `seq` (the resync point).
- **`BoardView`:** size and terrain. It is sent **only in a `CombatSnapshot`**,
  `{board, view, legal}`, because terrain never changes during a fight.
- **`CombatUpdate`:** pushed after every action as `{combat_id, from_seq, events[],
  view, legal}`.
  - The events are the engine's log events, each with its `seq`. They are for animation
    and the log.
  - The client renders state from `view`, so **no rules logic runs in TypeScript**.
- **`CombatLegal`:** the active unit's legal actions.
  - Moves are destinations, each with its cost and opportunity-attack warnings.
  - Attacks come with a cover flag, and ability targets are included.
- **Intents** (`CombatIntent`): `move {to}`, `attack {weapon, target}`,
  `ability {ability, target_unit?, target_square?}`, `wait`, `skip`.
- **No fog of war in v1:** every subscriber sees the whole combat.

### Timers
The engine has no clock (rule 2). The worker runs one `asyncio` timer per activation
and, on expiry, applies `Skip` as if the player had sent it. The timer is **disabled
for hotseat**. PvP will use `rules.activation_timer_s`.

### Lifecycle
| Status | Meaning | Transition |
|---|---|---|
| `active` | being played | created by `POST /api/combats/demo` |
| `finished` | the engine reported an outcome | written immediately, with the outcome |
| `abandoned` | no action for `combat_idle_timeout` (default 24 h) | idle sweeper in the worker |
| `aborted` | can't be replayed (content or rules changed) | during recovery |

Instances that are finished, abandoned or aborted are dropped from worker memory. Their
records stay in the DB.

### Persistence and recovery
- **Tables:**
  - `combats`: `combat_id` (UUID PK), `owner_user_id`, `mode` (`hotseat`),
    `status`, `worker_slot`, `setup` (JSON), `seed`, `content_hash`,
    `rules_version`, `outcome` (JSON, null), `created_at`, `updated_at`,
    `finished_at`;
  - `combat_actions`: `combat_id`, `seq` (the action number), `action` (JSON); primary
    key `(combat_id, seq)`.
- **Writes:**
  - **Immediate:** creation and finishing write the `combats` row.
  - **Write-behind:** each worker batches its pending `combat_actions` and flushes every
    1–2 s, at combat end, and on shutdown.
- **Recovery is lazy.** At worker start (gateway start, or a single worker's
  restart):
  1. One `UPDATE` marks the slot's `active` combats `aborted` when their
     `content_hash` or `rules_version` differs from the running server, because replay
     can't be exact. Nothing else is loaded, so start-up time doesn't depend on how many
     fights were in flight.
  2. A combat is rebuilt (`engine.resume` over its record) the **first time it's
     touched** (subscribe or intent). Concurrent first touches share one load. A record
     that fails to replay is marked `aborted`.
  - **Why lazy:** eager recovery of ~90 long fights per worker took longer than the
    60 s readiness timeout during the load test, and the server refused to start.
    Lazy recovery also leaves abandoned fights out of memory until someone comes back.
  - **Cost:** replay time grows with a fight's length (about 3–5 ms per action), and it
    runs on the worker's loop. A mass reconnect after a restart replays everything at
    once; see Open questions (checkpoints).

---

## Internal IPC (gateway ↔ workers)

- **Transport:** asyncio streams over **localhost TCP** (a Unix socket on Linux), with
  length-prefixed JSON frames.
  - This is the same on Windows dev machines and Linux servers. asyncio can't
    `add_reader` on Windows pipes.
  - The gateway listens; each worker connects back after spawn.
- **Messages** are Pydantic models in `workers/ipc.py`. They are **internal**: not part
  of the client protocol, and not generated into TypeScript.

  | Direction | Messages |
  |---|---|
  | gateway → worker | `hello_ack`, `create {combat_id, owner, setup, seed?}`, `intent {request_id, user_id, combat_id, action}`, `snapshot_request {combat_id, last_seq?}`, `close {combat_id}`, `ping`, `drain` |
  | worker → gateway | `hello {slot, boot_token}`, `reply {request_id, ok, reason_key?}`, `pushed {combat_id, update}` (`update`: `CombatUpdate` as JSON text, forwarded unparsed), `load_report {instances}`, `pong` |

- **Authentication:** the listener binds to localhost or a Unix socket only. A worker's
  `hello` must carry the per-boot random `boot_token` that the gateway passed at spawn.
- **Supervision:**
  - the gateway pings every 5 s;
  - a worker that misses 3 pings, or exits, is restarted with exponential backoff (1 s up
    to 30 s);
  - on shutdown the gateway sends `drain`: workers flush write-behind, close and exit.
- **The `CombatBackend` interface** used by `CombatRouter` has two implementations:
  - `ProcessBackend` (production) speaks IPC to the workers.
  - `InProcessBackend` (**unit tests only**) hosts a `CombatHost` in the gateway
    process, so router logic is testable without spawning processes.

  Integration tests use real processes.

---

## WebSocket gateway

One endpoint, `/ws`, for all realtime traffic. The message catalogue and envelope are in
[protocol](protocol.md); this section covers the lifecycle.

### Lifecycle
1. **Connect:** the gateway accepts the socket.
2. **Handshake:** the client's first message must be `hello {protocol_version,
   access_token}`, within **5 s**. On success the server answers `welcome {user,
   protocol_version}`.
3. **Session:** the client subscribes to combats and sends intents; the server pushes.
4. **Token refresh:** before the access token expires, the client sends `auth.refresh
   {access_token}` with a fresh token. At expiry without one, the server closes with
   4401. The client then refreshes over HTTP and reconnects.
5. **Close:** either side may close. The client reconnects with backoff and
   re-subscribes with `last_seq`.

### Close codes
| Code | Meaning | Client reaction |
|---|---|---|
| 4400 | malformed or unknown message | report a bug; reconnect |
| 4401 | auth failed or token expired | refresh over HTTP, then reconnect |
| 4408 | no `hello` within 5 s | reconnect |
| 4426 | protocol version mismatch | reload the page (new client build) |
| 4429 | rate limit exceeded | back off, then reconnect |
| 1011 | server error | reconnect with backoff |

### Connection management
- **Outbound queue:** each connection has a bounded `asyncio.Queue` (256 messages) and
  one writer task.
  - On overflow (a slow or stalled client), the connection is closed with 1011.
  - The client resyncs on reconnect. A slow client never holds back others.
- **Heartbeat:** the server sends a WebSocket ping every 20 s and closes connections
  idle for 60 s.
- **Watchdog:** a single gateway task checks every connection twice a second for token
  expiry (no `auth.refresh` in time, 4401) and idleness (1001). One task for all
  sockets replaced a timer task per connection.
- **Rate limit:** a per-connection token bucket, 20 messages/s with a burst of 40.
  Excess closes with 4429.
- **Several tabs per user** are allowed. Every subscribed connection receives the
  pushes.
- **Resync:** `combat.subscribe {combat_id, last_seq?}`.
  - If the worker's log still has every event after `last_seq`, the client gets those
    events.
  - Otherwise (a new client, or the gap is too large) it gets a fresh `combat.snapshot`
    plus `combat.legal`.

---

## Scalability and capacity model

**Target:** **1,000 concurrent players** on one machine.

### Why the engine can't run in the gateway
- **Measured cost before optimization:** the ground-combat engine took about
  **18–24 ms per action**, including the legal-action recompute after each action.
- **After optimization:** **mean 3.45 ms, p50 3.4 ms, p95 7.1 ms, p99 8.5 ms** per turn
  on 32×32 (`server/app/cli/bench_combat.py`, 20 seeded fights, dev box). The fixes:
  - one legal computation per state, memoized by state identity;
  - incremental opportunity-attack previews over the pathfinding tree;
  - a precomputed movement box;
  - an exact integer line walk for LoS (checked against a brute-force oracle);
  - per-board terrain grids;
  - hook dispatch that skips events nobody listens to.

  The rules didn't change: the golden-fight hash is identical.
- **Expected load:** 1,000 players mostly in turn-based fights, each acting every
  3–10 s, make **100–300 actions/s**.
- **The result:** before optimization that was 2–6 s of CPU per second. Even now it is
  about 1 s/s, while one Python process uses one core (the GIL). Running inline, every
  engine call would also delay every socket on the loop.

### Budgets
| Item | Budget | How |
|---|---|---|
| Combat actions | **300 actions/s** peak sustained | spread over combat workers |
| Engine | `apply_action` + legal recompute **≤ 8 ms p95** on 32×32 (measured 7.1 ms; the original 5 ms target was revised) | `bench_combat.py` on a dev box; `test_perf.py` guards regressions with a generous CI bound. Next levers if needed: compute area-ability target squares only when the ability is selected (they are about 20% of a slow turn), or a compiled pathfinder |
| Per worker | ~290 actions/s at the 3.45 ms mean | 3 workers ≈ 870 actions/s, about 3× headroom over the target |
| Intent → events | **p95 < 100 ms** end to end | gateway does routing and JSON only |
| Gateway | 1,000 sockets, ≤ 20 msg/s each worst case | no engine calls and no argon2 on its loop; bounded queues |
| DB | `DB_POOL_GATEWAY + N × DB_POOL_WORKER` connections | combat writes batched; auth writes are rare |
| Memory | a few hundred KB per combat, including its log | 1,000 combats ≈ a few hundred MB |

### Load test
- **The tool:** `server/app/cli/loadtest.py` runs asynchronous bot clients.
  - Each bot opens its demo combat over HTTP, connects to `/ws` and plays random legal
    actions with a randomized think time. It starts a new demo when one ends.
  - **Sign-in is not tested.** Per-IP auth rate limits make 1,000 sign-ups from one host
    impossible by design, and argon2 isn't what's measured. So the tool creates its bot
    users (`lt_<n>`, or `--user-prefix`) directly in `DATABASE_URL` and mints access
    tokens with `AUTH_SECRET`. Point both at a scratch DB.
  - Options: `--bots`, `--duration`, `--ramp`, `--think-ms`, `--procs` (load-generator
    processes), `--user-prefix` (a fresh set of fights), `--json`.
- **What it reports:** actions/s and intent → `combat.events` latency (p50/p95/p99/max)
  over the steady window after the ramp, `combat.events` frame sizes, finished combats,
  and errors by reason.
- **Its role:** it is **the gate** before raising player caps, and it runs before every
  release that touches the engine or the gateway.

#### Results (2026-11-25)
**Setup.** Everything ran on one dev box: an Intel i5-10400T (6 cores, 12 threads,
2.0 GHz) with 7.7 GB RAM, Windows 11 and Python 3.13.
- The gateway, 11 workers and the load generator shared the machine.
- The DB was a scratch SQLite file. Docker wasn't running, and the live Supabase DB is
  off limits for load tests.
- Each run used 1,000 bots with a 3 s mean think time, a 30 s ramp and 120 s measured.

| Run | Actions/s | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|
| Before the fixes below | 333.6 | 14.7 ms | 231 ms | 708 ms | 0 |
| + raw JSON forwarding, one watchdog | 337.8 | 9.8 ms | **45 ms** | 125 ms | 0 |
| repeat (placement still skewed) | 335.6 | 12.8 ms | 143 ms | 392 ms | 0 |
| + placement counted at decision | 337.9 | 9.7 ms | **46 ms** | 174 ms | 0 |
| repeat, with 1,000 earlier fights still resident | 337.0 | 10.1 ms | 115 ms | 394 ms | 0 |

- **Throughput: met.** About 337 actions/s were sustained against the 300/s budget,
  with all 1,000 sockets connected and no errors. `combat.events` frames averaged
  4.7 KB (p95 8.9 KB).
- **Latency: met on fresh load, but sensitive.** p95 was 45–46 ms with fresh fights
  and 115 ms with twice as many fights resident in the workers. The causes, in order:
  1. **CPU contention.** The load generator shares 6 cores with 12 server processes.
     Splitting it into 4 processes (`--procs 4`) made p95 *worse* (300 ms).
  2. **Worker GC pauses.** A full collection over a worker holding 180 fights (60k
     events) takes about 43 ms, and the pause grows with resident fights.
  3. **Windows' Proactor loop.** In the gateway profile, socket sends were the largest
     cost (about 0.36 ms per send).
- **Gateway CPU** fell from 77% to 43% of one core at the same rate, from raw JSON
  forwarding and the single watchdog.
- **Restart storm.** Resuming 1,000 long fights at once (every bot's first touch
  replays its record) pushed p99 to 2.2 s while workers replayed. See Open questions.
- **Fixes found by the load test:**
  - raw JSON push forwarding;
  - a single watchdog task;
  - placement counted at decision time;
  - lazy recovery, after eager recovery blocked start-up past the 60 s readiness
    timeout.
- **Still to do:** run on the target environment before raising caps:
  - Linux with uvloop;
  - Postgres;
  - the load generator on a separate machine.

### Beyond one machine (not needed for 1k)
- Several gateways would need cross-gateway pub/sub (for example Redis) for fan-out,
  plus sticky routing.
- Workers could then live on other hosts, with the IPC moved to the network.
- This is listed under Open questions.

---

## Database

- **Engine:** Supabase Postgres through SQLAlchemy 2.0 async (the asyncpg driver), with
  Alembic for migrations (`render_as_batch=True`, rule 10).
  - **One sanctioned exception to rule 10:** migrations enable row-level security with
    Postgres-only `ALTER TABLE … ENABLE ROW LEVEL SECURITY`, guarded by a dialect check
    (see `b3d9e6a41c27_auth_and_rls`). SQLite has no RLS and doesn't need it.
  - The debug `gen_*` tables get the same treatment when they're created.
- **Connection string:** `DATABASE_URL` from the environment or the repo-root `.env`.
  Plain `postgresql://` URLs are rewritten to `postgresql+asyncpg://`.
- **Pooler:** connect through Supabase's **Session pooler** (IPv4, port 5432), because
  the direct `db.<ref>.supabase.co` host is IPv6-only. The transaction pooler (6543) would
  need asyncpg's prepared-statement cache disabled.
- **Engines:** each process (the gateway and every worker) creates its own engine with
  its own pool size. Engines are never shared across processes.
- **Code locations:** engine and session factory in `server/app/persistence/db.py`;
  models in `server/app/persistence/models/`; migrations in `server/migrations/`.
- **Tests** run against SQLite (aiosqlite) to keep the models portable across database
  dialects.

### Schema
| Table | Purpose |
|---|---|
| `users` | `user_id` BIGINT identity PK · `username` VARCHAR(32) · `username_normalized` VARCHAR(32) unique (**new**) · `hashed_password` VARCHAR(255) · `role` VARCHAR(16) default `player` (**new**) · `created_at` (**new**) |
| `refresh_tokens` | (**new**) see [Refresh tokens](#refresh-tokens) |
| `combats`, `combat_actions` | (**new**) see [Persistence and recovery](#persistence-and-recovery) |
| `worlds`, `worldgen_pins`, `body_names` | world-gen deltas ([world-gen](world-gen.md)) |
| `gen_*` | debug world snapshot, never read by the game ([world-gen](world-gen.md)) |
| `identities` | (**later**) other sign-in methods |

### Write rules
- **Immediate and atomic:** registration, refresh rotation, logout, combat creation and
  finishing. Economic transactions will be too, when the economy exists (rule 5).
- **Write-behind:** gameplay deltas (combat actions now; world-sim deltas later) are
  batched by the process that owns them.

---

## Failure modes

| Failure | Effect | Recovery | Data at risk |
|---|---|---|---|
| Worker crash | its combats are unavailable for a few seconds; in-flight intents get `error {combat.unavailable}` | the supervisor restarts the worker; each combat is replayed on its next subscribe or intent; subscribers get `combat.snapshot` | actions since the last flush (≤ 2 s) |
| Gateway crash | every connection drops; workers lose their parent and exit | the process manager restarts the gateway; it respawns the workers (ready in seconds; combats replay lazily); clients reconnect and resync | actions since the last flush |
| DB unavailable | logins and refreshes fail (`503`); combats keep running in memory | write-behind retries with backoff and buffers in memory | everything unflushed, if a crash happens during the outage |
| Content or rules changed between restarts | affected combats can't be replayed exactly | marked `aborted` with a reason | those combats |

---

## Security checklist
- HTTPS and WSS only in production. Cookie flags as in
  [Refresh tokens](#refresh-tokens).
- JWT with a pinned algorithm, short lifetime, held in memory only; refresh-token
  rotation with reuse detection.
- Argon2id for passwords, in a thread pool; constant-time login; generic errors.
- Pydantic validation of every HTTP body and WebSocket message. Never trust client
  positions, quantities or results (rule 1).
- Rate limits on auth endpoints and per WebSocket connection; bounded queues everywhere.
- Secrets only in `.env`, never logged.
- The IPC listener binds to localhost or a Unix socket, with a per-boot token.
- **Supabase RLS enabled on every public table.** Supabase exposes `public` tables
  through its REST API to the anon key. Without RLS, `users.hashed_password` could leak.
  The server connects as `postgres` and isn't affected by RLS. Every migration that adds
  a table also enables RLS on it, with no policies.

---

## Testing strategy
- **Auth:**
  - unit tests: hashing and rehash, token claims and expiry, algorithm pinning, refresh
    rotation, reuse revoking the family;
  - API tests through the httpx ASGI transport.
- **WebSocket gateway:** handshake, every close code, rate limit, queue overflow, resync
  with and without `last_seq` (Starlette `TestClient` websockets).
- **Combat router** on `InProcessBackend`: placement, forwarding, fan-out to several
  tabs, seat errors, `IllegalAction` replies going to the sender only.
- **Process integration:**
  1. Start the gateway with 2 real workers.
  2. Play the demo combat.
  3. Kill a worker mid-fight.
  4. Assert that recovery by replay reproduces the live state, and that subscribers get a
     snapshot.
- **Engine:** a performance benchmark (`bench_combat.py`) and a guard test (`test_perf.py`) for the 8 ms p95 budget.
- **Load test** (manual or nightly), as above.

---

## Implementation phases
1. **Auth backend:** the `users` changes, `refresh_tokens`, migration (with RLS), auth
   endpoints and dependencies.
2. **Client login/register and the lobby:** galaxy button wired, combat-demo
   placeholder.
3. **Engine performance work** (done: p95 7.1 ms, mean 3.45 ms).
4. **Combat workers:** IPC, supervisor, `CombatHost`/`CombatInstance`, persistence and
   recovery, `content/combat/demo.toml`, `/api/combats`.
5. **WebSocket gateway:** protocol messages and codegen.
6. **Combat scene in the client:** hotseat demo.
7. **Load test** against the budgets.

---

## Open questions
- Tick rates for the world sim (fast/slow), and the world-sim process design (sector
  sharding, handoff of moving ships).
- PvP: matchmaking, activation timers, AFK handling and forfeits, reconnect grace
  periods.
- Spectators and replays shown to other players.
- Scaling beyond one machine (Redis pub/sub between several gateways, remote workers).
- Hosting and deployment (process manager, TLS termination, backups).
- Metrics and observability (structured logs, request ids, latency histograms).
- **Combat checkpoints.** Replay cost grows with a fight's length, so a mass reconnect
  after a restart is slow. The fix is to persist a periodic state snapshot (for example
  every 50 actions) and replay only the tail. It needs a state codec and a
  rules-version guard.
- **Worker GC tuning.** Pauses grow with resident fights (about 43 ms per full
  collection at 180 fights). Options: raise the GC thresholds, `gc.freeze()` after
  loading, or slimmer event logs (trimming events older than the catch-up window).
- Bringing back Telegram sign-in, and adding social login via Authlib.
