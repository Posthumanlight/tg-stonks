# Space Combat

Turn-based ship-to-ship combat.

## Decided
- Turn-based, server-authoritative, instanced: a combat is a self-contained state
  machine spawned from the world sim.
- Rules engine lives in `server/app/combat/space/`, pure and seeded; all rolls logged
  for replay.
- Ship hulls, modules and weapons are defined in `content/`.

## Open questions
- Turn structure: simultaneous orders resolved together, or alternating?
- Battlefield: abstract range bands or a 2D grid with positioning?
- Ship stats (hull, shields, energy, speed, evasion) and module slots.
- Weapon types, damage model, critical hits.
- Turn timers for async/offline players; retreat and fleet combat rules.
- PvP vs PvE rules and where PvP is allowed.
