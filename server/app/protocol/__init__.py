"""Client-server message schemas: the single source of truth for the client's TS types.

Any change here: regenerate (`npm run gen:protocol` in client/), bump PROTOCOL_VERSION
and update docs/protocol.md.
"""

PROTOCOL_VERSION = 2  # v2: auth, combats, WebSocket messages
