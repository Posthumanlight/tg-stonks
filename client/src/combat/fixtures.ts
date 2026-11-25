// Test fixtures for combat views (used by *.test.ts only; not imported by the app).
import type { CombatLegal, CombatView, UnitView } from "../protocol";

export function unit(overrides: Partial<UnitView> & Pick<UnitView, "uid">): UnitView {
  return {
    unit_type: "line_troopers",
    side: 0,
    origin: [0, 0],
    size: 1,
    models: 5,
    groups: [{ role: "trooper", alive: 5, initial: 5, hp: 1 }],
    wounded: null,
    statuses: [],
    reactions: 1,
    ...overrides,
  };
}

export function legal(overrides: Partial<CombatLegal> = {}): CombatLegal {
  return { unit: 1, moves: [], attacks: [], abilities: [], can_wait: true, ...overrides };
}

export function view(overrides: Partial<CombatView> = {}): CombatView {
  return {
    combat_id: "c1",
    seq: 10,
    round: 1,
    units: [unit({ uid: 1, origin: [2, 2] }), unit({ uid: 2, side: 1, origin: [6, 2] })],
    overlays: [],
    round_order: [1, 2],
    queue: [2],
    wait_queue: [],
    active: {
      uid: 1,
      movement_left: 6,
      ap_left: 2,
      weapons_used: [],
      moved: false,
      acted: false,
      attacked: false,
      movement_locked: false,
    },
    outcome: null,
    ...overrides,
  };
}
