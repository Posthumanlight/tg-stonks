# Ground Combat

Turn-based squad combat on planet surfaces in the style of tabletop wargames
(Warhammer 40k-like), using original rules and units.

## Decided
- Turn-based, server-authoritative, instanced; rules engine in
  `server/app/combat/ground/`, pure and seeded; every dice roll logged for replay.
- Squad-based: players command squads of units, not single heroes.
- Activation model: alternating activations.
- Unit types and wargear are defined in `content/`.

## Open questions
- Board: square grid vs hex grid; map size suitable for a phone screen.
- Line of sight and cover rules.
- Phase structure per activation (move → shoot → charge → fight?).
- Stats (movement, toughness, save, wounds, leadership) and the dice mechanic.
- Morale / suppression.
- Squad persistence: veterancy, casualties, reinforcement costs (ties into economy).
- Turn timers for async/offline players.
