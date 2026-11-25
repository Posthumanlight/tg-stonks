// Combat board colours. Terrain ids come from content/combat/terrain.toml; unknown ids
// fall back to a neutral tone so new content still renders.

export const COMBAT_COLOURS = {
  background: "#0b0f14",
  gridLine: 0x000000,
  unknownTerrain: 0x3a3f47,
  overlay: 0xc8ccd2,
  move: 0x58c27d,
  moveProvokes: 0xe0a24f,
  target: 0xff5a4f,
  abilitySquare: 0x4fa3e0,
  active: 0xffd34f,
  inspected: 0xffffff,
  wounded: 0xff3b30,
  unitText: "#ffffff",
} as const;

const TERRAIN: Readonly<Record<string, number>> = {
  open: 0x2e3b2c,
  rubble: 0x4b463d,
  forest: 0x1f4a2a,
  low_wall: 0x6a6357,
  wall: 0x8e887a,
  deep_water: 0x1c3a5e,
};

/** Side colours by side index; repeats past the end. */
const SIDES = [0x4f8fe0, 0xe0564f, 0x58c27d, 0xb57fe0, 0xe0c24f, 0x4fd0d0];

export const terrainColour = (id: string): number => TERRAIN[id] ?? COMBAT_COLOURS.unknownTerrain;

export const sideColour = (side: number): number => SIDES[side % SIDES.length] ?? 0xffffff;

/** CSS form of a side colour, for the DOM overlay. */
export const sideCss = (side: number): string =>
  `#${sideColour(side).toString(16).padStart(6, "0")}`;
