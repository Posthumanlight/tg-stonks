// Chart colours and sizes. Star `colour` values come from content/worldgen/stars.toml.

export const CHART_COLOURS = {
  background: 0x05070d,
  clusterFill: 0x3a5a9a,
  clusterStroke: 0x4d6aa8,
  lane: 0x4a6aa0,
  bridge: 0xd9a441,
  selection: 0xffd76a,
  label: "#8fa3c7",
  starLabel: "#c9d6ee",
} as const;

const STAR_COLOURS: Readonly<Record<string, number>> = {
  blue: 0x9bb0ff,
  blue_white: 0xaabfff,
  white: 0xf4f6ff,
  yellow_white: 0xfff1d8,
  yellow: 0xffe08a,
  orange: 0xffb46b,
  red: 0xff8064,
};

/** Screen radius in px by spectral class (hotter = bigger). */
const STAR_RADIUS_PX: Readonly<Record<string, number>> = {
  O: 7,
  B: 6,
  A: 5,
  F: 4.5,
  G: 4.5,
  K: 4,
  M: 3.5,
};

export const starColour = (colour: string): number => STAR_COLOURS[colour] ?? 0xffffff;
export const starRadiusPx = (starClass: string): number =>
  STAR_RADIUS_PX[starClass] ?? 4;
