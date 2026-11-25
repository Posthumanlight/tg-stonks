// The placement rule, mirrored from the server's `placement_issue` (server/app/combat/
// ground/setup.py) for instant hints while dragging. Hints only: the server re-validates
// on Start (CLAUDE.md rule 1). testdata/placement_cases.json runs against both.
import type { DeployZone } from "../protocol";

export type Square = readonly [number, number];
/** [x, y, w, h] */
export type Rect = readonly [number, number, number, number];

export interface PlacementBoard {
  readonly width: number;
  readonly height: number;
  readonly terrain: readonly string[];
}

export const squareKey = ([x, y]: Square): string => `${x},${y}`;

/** Squares of a size×size footprint whose top-left square is `origin`. */
export function footprint(origin: Square, size: number): Square[] {
  const squares: Square[] = [];
  for (let dy = 0; dy < size; dy++) {
    for (let dx = 0; dx < size; dx++) squares.push([origin[0] + dx, origin[1] + dy]);
  }
  return squares;
}

const inBounds = (board: PlacementBoard, [x, y]: Square): boolean =>
  x >= 0 && y >= 0 && x < board.width && y < board.height;

const inRect = ([x, y]: Square, [rx, ry, rw, rh]: Rect): boolean =>
  x >= rx && x < rx + rw && y >= ry && y < ry + rh;

/** Why the footprint can't go there (a `setup.*` reason key), or null. Same check order
 * as the server: bounds, terrain, zone, overlap. */
export function placementIssue(
  board: PlacementBoard,
  passable: Readonly<Record<string, boolean | undefined>>,
  origin: Square,
  size: number,
  occupied: ReadonlySet<string>,
  zone: readonly Rect[] | null,
): string | null {
  const squares = footprint(origin, size);
  if (!squares.every((s) => inBounds(board, s))) return "setup.out_of_bounds";
  if (!squares.every(([x, y]) => passable[board.terrain[y * board.width + x] ?? ""] === true)) {
    return "setup.blocked_square";
  }
  if (zone && !squares.every((s) => zone.some((r) => inRect(s, r)))) return "setup.outside_zone";
  if (squares.some((s) => occupied.has(squareKey(s)))) return "setup.overlap";
  return null;
}

/** A side's deployment zone; null when the map has none (the whole board is allowed). */
export function zoneFor(zones: readonly DeployZone[] | null, side: number): Rect[] | null {
  if (!zones) return null;
  return zones.find((z) => z.side === side)?.rects ?? [];
}
