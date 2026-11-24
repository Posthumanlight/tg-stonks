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
| `POST /api/combats/demo` | Bearer | `{combat_id}` | **planned**: creates or returns the user's hotseat demo combat |
| `GET /api/combats` | Bearer | `[{combat_id, mode, status, …}]` | **planned**: the user's active combats |

HTTP errors use the body `{reason_key, detail?}` with a fitting status (400, 401, 403,
404, 409, 429 + `Retry-After`, 503).

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

### Messages (v1)
| Direction | Type | Payload | Notes |
|---|---|---|---|
| C → S | `hello` | `{protocol_version, access_token}` | must be first |
| C → S | `auth.refresh` | `{access_token}` | replaces the connection's token |
| C → S | `ping` | `{}` | application-level keepalive (optional) |
| C → S | `combat.subscribe` | `{combat_id, last_seq?}` | needs a seat. Replies with missed `combat.events` or a `combat.snapshot` |
| C → S | `combat.unsubscribe` | `{combat_id}` | |
| C → S | `combat.action` | `{combat_id, action}` | `action` is one of `move {path}`, `attack {weapon, target}`, `ability {ability, target_unit?, target_square?}`, `wait`, `skip` |
| S → C | `welcome` | `{user, protocol_version}` | |
| S → C | `ack` | `{id}` | the request was accepted |
| S → C | `error` | `{id?, reason_key, detail?}` | `id` present when it answers a request |
| S → C | `pong` | `{}` | |
| S → C | `combat.snapshot` | `CombatView` | full state, including `last_seq` |
| S → C | `combat.events` | `{combat_id, from_seq, events[]}` | engine log events, each with its `seq` |
| S → C | `combat.legal` | `{combat_id, legal}` | the active unit's legal actions (moves, attacks, abilities, can_wait) |

Combat-specific error reasons include `combat.not_your_turn`, `combat.unavailable`
(the worker is restarting; retry) and `combat.not_found`, plus every engine reason key
(`move.forbidden.*`, `attack.forbidden.*`, `ability.forbidden.*`, …).

### Close codes
4400 malformed or unknown message · 4401 auth failed or token expired · 4408 no `hello`
in time · 4426 protocol version mismatch (reload) · 4429 rate limited · 1011 server
error or outbound queue overflow.

### Limits
- 20 messages/s per connection, burst 40; excess closes with 4429.
- The outbound queue holds 256 messages per connection.
- The server pings every 20 s and drops connections idle for 60 s.

## Open questions
- Binary encoding (MessagePack) once message volume justifies it.
- World-sim deltas (sector subscriptions): full entity snapshots vs field-level diffs.
- Spectator subscriptions and fog of war in combat views.
