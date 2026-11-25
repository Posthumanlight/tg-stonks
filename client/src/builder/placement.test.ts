import { describe, expect, it } from "vitest";

// The same cases run on the server (server/tests/combat/ground/test_deployment.py).
import fixture from "../../../testdata/placement_cases.json";
import { type Rect, placementIssue, squareKey, zoneFor } from "./placement";

interface Case {
  name: string;
  origin: [number, number];
  size: number;
  occupied: [number, number][];
  zone: Rect[] | null;
  expect: string | null;
}

const board = {
  width: fixture.rows[0]?.length ?? 0,
  height: fixture.rows.length,
  terrain: fixture.rows.flatMap((row) => [...row].map((c) => (c === "#" ? "wall" : "open"))),
};
const passable = { open: true, wall: false };

describe("placementIssue (shared fixture)", () => {
  it.each(fixture.cases as Case[])("$name", (c) => {
    const occupied = new Set(c.occupied.map(squareKey));
    expect(placementIssue(board, passable, c.origin, c.size, occupied, c.zone)).toBe(c.expect);
  });
});

describe("zoneFor", () => {
  it("is null without zones, empty for a side without one", () => {
    expect(zoneFor(null, 0)).toBeNull();
    expect(zoneFor([{ side: 1, rects: [[0, 0, 2, 2]] }], 0)).toEqual([]);
    expect(zoneFor([{ side: 1, rects: [[0, 0, 2, 2]] }], 1)).toEqual([[0, 0, 2, 2]]);
  });
});
