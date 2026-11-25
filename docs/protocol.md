# Protocol

The client–server contract: the HTTP endpoints, the WebSocket envelope and messages,
and versioning. Server processes and the lifecycle of connections and combats are in
[architecture](architecture.md).

## Decided
- **Transport:** WebSocket (`/ws`) for realtime gameplay; HTTP (`/api`) for auth,
  account and static data. Both share the client's origin.
- **Client → server:** intents only (e.g. `combat.action`). The server validates them
  and resolves them (CLAUDE.md rule 1).
- **Server → client:** pushes for what the connection is subscribed to (combat events,
  legal actions, snapshots).
- **Source of truth:** Pydantic models in `server/app/protocol/`. The TS types in
  `client/src/protocol/` are generated (`npm run gen:protocol`) and never hand-edited.
- **Versioning:** any message change bumps `PROTOCOL_VERSION`. A client with a different
  version gets close code 4426 and must reload.
- **Encoding:** JSON. A binary format (MessagePack) is an open question for later.
- **Codegen pipeline:**
  - Models subclass `ProtocolModel` (`server/app/protocol/base.py`: frozen, no extra
    fields) and are listed in `PROTOCOL_MODELS` (`server/app/protocol/registry.py`).
  - `server/app/cli/export_schema.py` prints their JSON Schema in serialization mode.
  - `client/scripts/gen-protocol.mjs` compiles it with `json-schema-to-typescript` into
    `client/src/protocol/index.ts`, plus `PROTOCOL_VERSION`.
  - `npm run gen:protocol -- --check` fails when the committed file is stale.
- **Error reasons:** every error carries a `reason_key`, an i18n key (for example
  `attack.forbidden.no_los`). The client shows `t(reason_key)`.

## HTTP endpoints
| Method and path | Auth | Response | Notes |
|---|---|---|---|
| `GET /api/health` | public | `HealthView` | `{status: "ok", protocol_version}` |
| `POST /api/auth/register` | public | `201 {user}` | `409` if the name is taken. See [architecture › Authentication](architecture.md#authentication) |
| `POST /api/auth/login` | public | `{access_token, expires_in, user}` + refresh cookie | generic `401 auth.invalid_credentials` |
| `POST /api/auth/refresh` | refresh cookie | `{access_token, expires_in, user}` + rotated cookie | same-origin `Origin` required |
| `POST /api/auth/logout` | refresh cookie | `204` | revokes this device's session |
| `POST /api/auth/logout-all` | Bearer | `204` | revokes every session of the user |
| `GET /api/auth/me` | Bearer | `{user}` | |
| `GET /api/world/galaxy` | Bearer | `GalaxyView` | built once at startup; strong `ETag`, `Cache-Control: no-cache`, `304` on `If-None-Match` |
| `GET /api/combats/builder` | Bearer | `BuilderView` | static data for the custom-battle builder (below); strong `ETag`, `304` on `If-None-Match` |
| `POST /api/combats/custom` | Bearer | `201 CombatCreated {combat_id}` | body `CustomCombatRequest`. `400 setup.*` with `detail {side, unit}`; `409 combat.already_active` |
| `POST /api/combats/demo` | Bearer | `CombatCreated {combat_id}` | quick battle: the default armies from `demo.toml`, or the user's active fight if there is one |
| `POST /api/combats/{id}/abandon` | Bearer | `204` | participants only (`403 combat.not_a_participant`); `409 combat.finished` if it isn't active. Hotseat: the fight ends without an outcome. Online (`pvp`): **surrender**, the opponent wins (`finished`) |
| `GET /api/combats` | Bearer | `[CombatSummaryView {combat_id, mode, status, created_at}]` | the combats the user owns or is seated in, newest first; `mode` is `hotseat` or `pvp` |
| `POST /api/rooms` | Bearer | `201 RoomJoined {room_id, code}` | body `CreateRoomRequest`. `400 room.bad_points` / `room.bad_timer` (not a preset); `409 room.already_in_room` / `combat.already_active` |
| `GET /api/rooms?q=&points=` | Bearer | `RoomList {rooms: [RoomCard]}` | open **public** rooms, newest first, at most 50; `q` matches the name (any case), `points` the limit exactly |
| `GET /api/rooms/mine` | Bearer | `MyRoom {room: RoomJoined \| null}` | the room the user is in (the lobby's "Back to your room") |
| `POST /api/rooms/join` | Bearer | `RoomJoined` | body `{code}`: any room, public or private (fast join). `404 room.not_found`, `409 room.full`, `403 room.kicked`, `429 room.rate_limited` (20 joins/min per user) |
| `POST /api/rooms/{id}/join` | Bearer | `RoomJoined` | a **public** room from search (private ones: `404`) |
| `POST /api/rooms/{id}/ready` | Bearer | `RoomReady {combat_id \| null}` | body `SideSetup`: lock in your army. `400 setup.*` with `detail {side, unit}` (zones, `setup.over_points`). `combat_id` is set when this made both players ready: the battle began |
| `POST /api/rooms/{id}/unready` | Bearer | `204` | unlock your army for editing |
| `POST /api/rooms/{id}/leave` | Bearer | `204` | the host leaving closes the room |
| `POST /api/rooms/{id}/kick` | Bearer | `204` | host only (`403 room.not_host`); the guest can't rejoin |

HTTP errors use the body `{reason_key, detail?}` with a fitting status (400, 401, 403,
404, 409, 429 + `Retry-After`, 503).

### Custom battle models
The models are in `server/app/protocol/builder.py`. The rules behind them are in
[combat-ground › Deployment and army building](combat-ground.md#deployment-and-army-building).

| Model | Fields |
|---|---|
| `BuilderView` | `board: BoardView` (its `factions` and `players` are `null` here), `terrain: {id: TerrainCard {passable}}`, `zones: [DeployZone] \| null` (hotseat: `null`), `factions: [FactionCard]`, `limits {max_units_per_side}`, `defaults: CustomCombatRequest`, `rooms: RoomPresets` |
| `RoomPresets` | `points_presets: [int]`, `timer_presets: [int]` (0 = unlimited in both), `default_timer_s`, `zones: [DeployZone] \| null` (where each side deploys in a room) |
| `DeployZone` | `side`, `rects: [[x, y, w, h]]`. `zones: null` means the whole board is allowed |
| `FactionCard` | `id`, `name_key`, `units: [UnitCard]` |
| `UnitCard` | `unit_type`, `name_key`, `points`, `footprint` (1 or 2), `models {min, max, default}` |
| `CustomCombatRequest` | `sides: [SideSetup]`. Exactly 2; the side number is the list index |
| `SideSetup` | `faction`, `units: [DeployedUnit]` |
| `DeployedUnit` | `unit_type`, `models`, `origin: [x, y]` (the footprint's top-left square) |

- A setup error answers `400 {reason_key, detail: {side, unit}}`. `unit` is the index in
  that side's `units`, or `null` for side-wide errors (`setup.empty_side`,
  `setup.too_many_units`, `setup.unknown_faction`).
- The points totals aren't sent. The client sums `UnitCard.points` itself, because points
  are a display-only figure in v1.

### Lobby room models
In `server/app/protocol/rooms.py`; the rules are in [lobby-rooms](lobby-rooms.md).

| Model | Fields |
|---|---|
| `CreateRoomRequest` | `name` (1–40), `private`, `points_limit`, `timer_s` (each one of the `RoomPresets`) |
| `RoomJoined` | `room_id`, `code` (6 characters) |
| `RoomCard` | `room_id`, `name`, `host_name`, `points_limit`, `timer_s` |
| `RoomView` | `room_id`, `code`, `name`, `private`, `points_limit`, `timer_s`, `status` (`open` \| `full` \| `starting`), `host_user_id`, `your_side`, `players: [RoomPlayer]`, `your_army: SideSetup \| null` |
| `RoomPlayer` | `user_id`, `name`, `side`, `ready`, `connected`, and, once ready, `faction`, `points`, `unit_count` (never positions) |

`RoomView` is rendered **per viewer**: only your own army comes back in full.

## WebSocket

### Envelope
Every frame is one JSON object:
```json
{ "type": "combat.action", "id": "c-17", "payload": { ... } }
```
- `type`: the message type (below). Unknown types close the connection with 4400.
- `id`: optional, client-chosen request id. A request with an `id` is answered by
  `ack {id, …}` or `error {id, reason_key}`. Server pushes have no `id`.
- `payload`: the message body; its model depends on `type`. In Pydantic this is a
  discriminated union on `type`.

### Lifecycle (summary; details in [architecture › WebSocket gateway](architecture.md#websocket-gateway))
1. **Connect** to `/ws`.
2. **Handshake:** within 5 s, send `hello {protocol_version, access_token}`. The server
   answers `welcome {user, protocol_version}`.
3. **Session:** subscribe, act and receive pushes. Send `auth.refresh {access_token}`
   before the access token expires.
4. **Reconnect:** on close, reconnect with backoff and re-subscribe with `last_seq`.

### Messages (`PROTOCOL_VERSION` 4)
- **Version 3** added the custom battle models and `BoardView.factions`.
- **Version 4** adds:
  - the lobby rooms (`room.*` messages, the room models, `BuilderView.rooms`);
  - `BoardView.players`;
  - `deadline_ms` on snapshots and updates.

The models are in `server/app/protocol/ws.py` (messages) and
`server/app/protocol/combat.py` (combat payloads).

| Direction | Type | Payload | Notes |
|---|---|---|---|
| C → S | `hello` | `{protocol_version, access_token}` | must be first, within 5 s |
| C → S | `auth.refresh` | `{access_token}` | replaces the connection's token (same user only) |
| C → S | `ping` | — | keepalive; answered with `pong` (send one every ~25 s) |
| C → S | `combat.subscribe` | `{combat_id, last_seq?}` | needs a seat. Pushes the missed `combat.events` (when `last_seq` is close enough) or a `combat.snapshot`, then `ack` |
| C → S | `combat.unsubscribe` | `{combat_id}` | |
| C → S | `room.subscribe` | `{room_id}` | members only (`room.not_member`). Pushes `room.state` now and on every change. Open subscriptions are the member's **presence** |
| C → S | `room.unsubscribe` | `{room_id}` | |
| C → S | `combat.action` | `{combat_id, intent}` | `intent` is one of `move {to}`, `attack {weapon, target}`, `ability {ability, target_unit?, target_square?}`, `wait`, `skip`. `move` names only the destination: the server uses the path it showed in `legal` |
| S → C | `welcome` | `{user_id, role, protocol_version}` | |
| S → C | `ack` | `id` (no payload) | the request was accepted; for an action, it arrives **after** that action's `combat.events` |
| S → C | `error` | `{reason_key, detail?}` + `id` | `id` is set when it answers a request |
| S → C | `pong` | `id` | |
| S → C | `combat.snapshot` | `CombatSnapshot {board, view, legal, deadline_ms}` | the only message carrying the board (terrain and seats never change during a fight). `board` (`BoardView {width, height, terrain, factions, players}`): each side's faction id (`null` for old records), and `players [{side, user_id, name}]`, which tell the client which sides it acts for (online: one; hotseat: all, `name` "") |
| S → C | `combat.events` | `CombatUpdate {combat_id, from_seq, events[], view, legal, deadline_ms}` | pushed to every subscriber after each action, including the server's auto-Skip when the timer runs out. `view` is the new state, so clients render from it and never re-implement rules; `events` (each with its `seq`) are for animation and the log. `deadline_ms`: when the active unit's timer runs out (epoch ms), `null` when untimed |
| S → C | `room.state` | `RoomView` | your view of your room (per viewer) |
| S → C | `room.started` | `{room_id, combat_id}` | both are ready: open the battle. The room is gone |
| S → C | `room.closed` | `{room_id, reason}` | `room.closed.host_left`, `.host_gone`, `.expired`, `.kicked`, `.gone` (your grace ran out), `.left` |

Combat error reasons:
- `combat.not_your_turn`;
- `combat.not_a_participant`;
- `combat.not_found`;
- `combat.finished`;
- `combat.unavailable`: the worker is restarting; retry;
- `combat.already_active`: the user already has an active battle of that mode (resume
  or abandon/surrender it first);
- `combat.bad_setup`;
- `setup.*`: a custom setup was rejected (the full list is in
  [combat-ground › Validation and errors](combat-ground.md#validation-and-errors));
- every engine reason key (`move.forbidden.*`, `attack.forbidden.*`,
  `ability.forbidden.*`, …).

Room error reasons: `room.not_found`, `room.full`, `room.kicked`, `room.not_member`,
`room.not_host`, `room.no_guest`, `room.locked` (the battle is starting),
`room.not_ready`, `room.already_in_room`, `room.bad_points`, `room.bad_timer`,
`room.rate_limited`, and `setup.over_points`.

Gateway errors:
- `protocol.version_mismatch` (sent before closing with 4426);
- `ws.already_authenticated`;
- `auth.forbidden`.

### Close codes
- **4400:** a malformed or unknown message.
- **4401:** auth failed, or the token expired without an `auth.refresh`.
- **4408:** no `hello` in time.
- **4426:** protocol version mismatch (reload).
- **4429:** rate limited.
- **1001:** idle for 60 s.
- **1011:** server error or outbound queue overflow.

### Limits
- 20 messages/s per connection, burst 40; excess closes with 4429.
- The outbound queue holds 256 messages per connection. A client that can't keep up is
  dropped, and it resyncs on reconnect.
- uvicorn sends WebSocket pings every 20 s, and the gateway closes connections that
  sent nothing for 60 s.

## Open questions
- Binary encoding (MessagePack) once message volume justifies it.
- World-sim deltas (sector subscriptions): full entity snapshots vs field-level diffs.
- Spectator subscriptions and fog of war in combat views.
