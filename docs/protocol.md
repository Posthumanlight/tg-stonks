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

## Open questions
- Envelope shape (`{type, seq, payload}`?) and request/response correlation.
- Encoding: JSON first, binary (MessagePack) later?
- Delta format: full entity snapshots vs field-level diffs; resync strategy after reconnect.
- Codegen tool choice (Pydantic → JSON Schema → TS).
- Rate limiting per connection.
