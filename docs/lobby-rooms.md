# Lobby rooms (online 1v1)

How players find each other for an online battle:
- **Create** a custom game (a room).
- **Search** the open public rooms.
- **Fast-join** any room by its code.

Each player then builds and deploys their own side, and the battle starts when both
are ready. Combat itself is unchanged; see [architecture › Combat modes](architecture.md#combat-modes).

A matchmaking queue is **not** part of this; it comes after release.

## Decided

### What a room is
- **Two seats.**
  - The **host** (the creator) is always side 0, which deploys in the top zone.
  - One **guest** is side 1, which deploys in the bottom zone.
  - There are no spectators and no side choice.
- **Settings, chosen by the host at creation:**

  | Setting | Values |
  |---|---|
  | name | 1–40 characters; whitespace is collapsed |
  | private | hidden from search; joinable **by code only** |
  | points limit | one of `rules.pvp.points_presets` (0 = unlimited) |
  | turn timer | one of `rules.pvp.timer_presets`, in seconds per activation (0 = unlimited) |

  The presets live in `content/combat/rules.toml` `[pvp]`. `activation_timer_s` must be
  one of them.
- **A 6-character code:**
  - Every room has one, made from `secrets` in the Crockford base32 alphabet (no I, L, O
    or U).
  - Input forgives case, spaces, dashes, and O→0 or I/L→1.
  - Public rooms are listed in search *and* joinable by code.
- **One room per user at a time.** No room may be joined while the user has an online
  battle running. Hotseat battles don't count toward either limit.

### Lifecycle
```
open ──guest joins──► full ──both ready──► starting ──► (battle starts; room removed)
 ▲                      │
 └── guest leaves, ─────┘          any ──host leaves / host gone / idle──► closed
     is kicked, or is gone
```
- **Ready** submits the player's army. It is validated *alone*:
  - faction, unit count, model ranges, and the room's points limit;
  - every unit inside the player's deployment zone.

  **Unready** unlocks it for editing. The host may ready before a guest arrives.
- **When the second player readies,** the room becomes `starting`:
  - The status is set before any await, so a battle starts only once, and leave, ready
    and kick are refused (`room.locked`).
  - The pair is re-validated with `deployment.deploy` (zones, points limit).
  - Then `CombatRouter.start` places a `pvp` combat with the seats and timer.
  - Both members get `room.started {combat_id}`, and the room is removed.
- **If the start fails** (for example, a player already has an online battle), the room
  goes back to `full`, both players are unready, and the error goes to whoever readied
  last.
- **The host can kick the guest,** who can't rejoin that room (`room.kicked`). The
  kicked guest's sockets get `room.closed {room.closed.kicked}`.

### Presence and expiry
- **Presence:** a member is present while one of their sockets is subscribed to the
  room (`room.subscribe`). When the last one goes, their grace period starts.
- **One sweeper** runs every 5 s on the gateway:

  | Case | After (content) | Result |
  |---|---|---|
  | guest disconnected | `guest_grace_s` (30) | seat freed; the room is open again (`room.closed.gone` to the guest) |
  | host disconnected | `host_grace_s` (60) | room closed (`room.closed.host_gone`) |
  | no change at all | `room_idle_ttl_s` (1800) | room closed (`room.closed.expired`) |

- **A room in `starting`** is never expired.
- **In battle, disconnects don't forfeit.** The turn timer keeps the fight moving, and
  an untimed fight that stalls ends after 24 h through the combat idle sweeper.

### Hidden deployment
- **What each member sees:** `RoomView` is rendered **per viewer**.
  - Your own locked army comes back in full (`your_army`), so a reconnect restores the
    builder.
  - For the opponent you see only their name, ready flag, connection, and, once they're
    ready, their faction, points and unit count. **Never their positions.**

### Storage
- **Rooms live in gateway memory** (`MemoryRoomStore`), behind the `RoomStore`
  interface. The gateway is a single process, so this is the source of truth.
- **A restart drops waiting rooms.** Started battles are persisted combats.
- **Scaling to several gateways** swaps in a shared store (for example Redis) behind the
  same interface.

### Code map
- `server/app/lobby/room.py` is the pure domain: `Room`, `Member`, transitions and
  expiry. It has no I/O and no clock of its own.
- `server/app/lobby/store.py` holds `RoomStore`, `MemoryRoomStore`, and the code helpers.
- `server/app/lobby/hub.py` holds `RoomHub`: subscriptions, per-viewer
  `room.state` pushes, `room.started` and `room.closed`.
- `server/app/lobby/service.py` holds `RoomService`: the use cases, the limits, the
  join rate limit (20 per minute per user, against code guessing), the battle start and
  the sweeper.
- `server/app/api/rooms.py` has the HTTP routes. `ws/router.py` handles
  `room.subscribe` and `room.unsubscribe`.
- **Why HTTP for changes and WebSocket only for watching:** HTTP errors already carry a
  located `setup.*` detail (`{side, unit}`) for a refused Ready. The socket is presence.

## Open questions
- Matchmaking queue (after release), and rating.
- Rematch in the same room; letting the host choose the side.
- Spectators, and chat with moderation.
- Forfeit on long disconnects in battle (today the timer only skips).
- Zone shapes per map once there's more than the demo map.
