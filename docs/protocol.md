# Protocol

The client–server contract: WebSocket message envelope, client intents, server
state deltas, and versioning.

## Decided
- Transport: WebSocket for gameplay; HTTP for auth, account and static data.
- Client → server: intents only (e.g. `move_to`, `place_order`, `activate_unit`).
- Server → client: state deltas for the subscribed sector/planet, plus combat events.
- Pydantic models in `server/app/protocol/` are the source of truth; TS types in
  `client/src/protocol/` are generated (`npm run gen:protocol`) and never hand-edited.
- Any message change bumps `PROTOCOL_VERSION`; mismatched clients are told to reload.
- **Codegen pipeline:**
  - Models subclass `ProtocolModel` (`server/app/protocol/base.py`: frozen, no extra
    fields) and are listed in `PROTOCOL_MODELS` (`server/app/protocol/registry.py`).
  - `server/app/cli/export_schema.py` prints their JSON Schema in serialization mode.
  - `client/scripts/gen-protocol.mjs` compiles that schema with `json-schema-to-typescript`
    into `client/src/protocol/index.ts`, plus `PROTOCOL_VERSION`.
  - `npm run gen:protocol -- --check` fails when the committed file is stale.

## HTTP endpoints
| Method and path | Response | Notes |
|---|---|---|
| `GET /api/health` | `HealthView` | `{status: "ok", protocol_version}` |
| `GET /api/world/galaxy` | `GalaxyView` | Built once at startup. Strong `ETag` and `Cache-Control: no-cache`; returns 304 on `If-None-Match`. |

## Open questions
- Envelope shape (`{type, seq, payload}`?) and request/response correlation.
- Encoding: JSON first, binary (MessagePack) later?
- Delta format: full entity snapshots vs field-level diffs; resync strategy after reconnect.
- Rate limiting per connection.
