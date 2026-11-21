# Economy

Resources, production chains, markets, and the NPC actors that keep the economy alive.

## Decided
- Hybrid model: NPC factions/planets produce and consume to provide a baseline;
  players participate in production chains and trade on markets.
- Items and recipes are data-driven (`content/*.toml`), validated at startup.
- Money and quantities are integers (minor units), never floats.
- Every currency/item movement goes through the ledger service; trades commit atomically.
- NPC actors use the same market API as players — no hidden side doors.
- Production runs on the slow tick.

## Open questions
- Resource tiers and chain depth (raw → refined → components → ships/modules?).
- Market model: order book per station? regional prices? transport costs?
- Currency faucets and sinks (taxes, repairs, fees, decay) to control inflation.
- Player-owned production facilities: where they live (planets, stations) and limits.
- NPC demand modelling and price discovery.
