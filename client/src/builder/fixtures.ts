// A small builder template for tests: an 8×6 open board with one wall, two factions.
import type { BuilderView, UnitCard } from "../protocol";

const card = (
  unit_type: string,
  points: number,
  footprint: number,
  min: number,
  max: number,
  def: number,
): UnitCard => ({
  unit_type,
  name_key: `unit.${unit_type}.name`,
  points,
  footprint,
  models: { min, max, default: def },
});

export const TROOPERS = card("line_troopers", 90, 1, 5, 10, 10);
export const WALKER = card("bastion_walker", 160, 2, 1, 1, 1);
export const SWARM = card("ravager_swarm", 80, 1, 10, 30, 20);

const ROWS = ["........", "...#....", "........", "........", "........", "........"];

export function builderView(overrides: Partial<BuilderView> = {}): BuilderView {
  return {
    board: {
      width: 8,
      height: 6,
      terrain: ROWS.flatMap((r) => [...r].map((c) => (c === "#" ? "wall" : "open"))),
    },
    terrain: { open: { passable: true }, wall: { passable: false } },
    zones: null,
    factions: [
      { id: "concord", name_key: "faction.concord.name", units: [TROOPERS, WALKER] },
      { id: "brood", name_key: "faction.brood.name", units: [SWARM] },
    ],
    limits: { max_units_per_side: 3 },
    defaults: {
      sides: [
        { faction: "concord", units: [{ unit_type: "line_troopers", models: 10, origin: [0, 0] }] },
        { faction: "brood", units: [{ unit_type: "ravager_swarm", models: 20, origin: [7, 5] }] },
      ],
    },
    rooms: {
      points_presets: [200, 0],
      timer_presets: [45, 0],
      default_timer_s: 45,
      zones: [
        { side: 0, rects: [[0, 0, 8, 2]] }, // top two rows
        { side: 1, rects: [[0, 4, 8, 2]] }, // bottom two rows
      ],
    },
    ...overrides,
  };
}
