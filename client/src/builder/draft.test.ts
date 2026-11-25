import { describe, expect, it } from "vitest";

import {
  draftIssues,
  dropIssue,
  fitsTemplate,
  moveUnit,
  placeUnit,
  removeUnit,
  setFaction,
  setModels,
  sidePoints,
  unitAtSquare,
} from "./draft";
import { TROOPERS, WALKER, builderView } from "./fixtures";

const view = builderView();
const draft = view.defaults;

describe("draft edits", () => {
  it("places, moves, resizes and removes units immutably", () => {
    const placed = placeUnit(draft, 0, WALKER, [4, 2]);
    expect(placed.sides[0].units).toHaveLength(2);
    expect(draft.sides[0].units).toHaveLength(1); // unchanged
    const moved = moveUnit(placed, { side: 0, index: 1 }, [5, 3]);
    expect(moved.sides[0].units[1]?.origin).toEqual([5, 3]);
    const resized = setModels(moved, { side: 0, index: 0 }, TROOPERS, 99);
    expect(resized.sides[0].units[0]?.models).toBe(10); // clamped to the range
    expect(removeUnit(resized, { side: 0, index: 0 }).sides[0].units).toHaveLength(1);
  });

  it("a new faction empties the side", () => {
    expect(setFaction(draft, 1, "concord").sides[1]).toEqual({ faction: "concord", units: [] });
  });

  it("finds units by any square of their footprint", () => {
    const placed = placeUnit(draft, 0, WALKER, [4, 2]);
    expect(unitAtSquare(view, placed, [5, 3])).toEqual({ side: 0, index: 1 });
    expect(unitAtSquare(view, placed, [6, 3])).toBeNull();
  });

  it("sums display points per side", () => {
    expect(sidePoints(view, placeUnit(draft, 0, WALKER, [4, 2]).sides[0])).toBe(250);
  });
});

describe("drop and draft issues", () => {
  it("checks a drop like the server, ignoring the unit being moved", () => {
    expect(dropIssue(view, draft, 0, 1, [3, 1])).toBe("setup.blocked_square");
    expect(dropIssue(view, draft, 0, 1, [0, 0])).toBe("setup.overlap");
    expect(dropIssue(view, draft, 0, 1, [0, 0], { side: 0, index: 0 })).toBeNull();
    expect(dropIssue(view, draft, 0, 2, [7, 0])).toBe("setup.out_of_bounds");
    const zoned = builderView({
      zones: [
        { side: 0, rects: [[0, 0, 8, 2]] },
        { side: 1, rects: [[0, 4, 8, 2]] },
      ],
    });
    expect(dropIssue(zoned, draft, 0, 1, [0, 3])).toBe("setup.outside_zone");
  });

  it("lists side-wide and per-unit problems in the server's order", () => {
    expect(draftIssues(view, draft)).toEqual([]);
    const empty = setFaction(draft, 1, "brood");
    expect(draftIssues(view, empty)).toEqual([{ side: 1, unit: null, reason: "setup.empty_side" }]);
    const clash = placeUnit(draft, 1, TROOPERS, [7, 5]); // wrong faction (checked first)
    expect(draftIssues(view, clash)).toEqual([{ side: 1, unit: 1, reason: "setup.wrong_faction" }]);
    const crowded = [1, 2, 3].reduce((d, x) => placeUnit(d, 0, TROOPERS, [x, 4]), draft);
    expect(draftIssues(view, crowded)).toContainEqual({
      side: 0,
      unit: null,
      reason: "setup.too_many_units",
    });
  });
});

describe("fitsTemplate", () => {
  it("accepts a valid saved draft and rejects stale or malformed ones", () => {
    expect(fitsTemplate(view, draft)).toBe(true);
    expect(fitsTemplate(view, null)).toBe(false);
    expect(fitsTemplate(view, { sides: [] })).toBe(false);
    const oversized = setModels(
      draft,
      { side: 0, index: 0 },
      { ...TROOPERS, models: { min: 1, max: 99, default: 1 } },
      50,
    );
    expect(fitsTemplate(view, oversized)).toBe(false);
    const gone = placeUnit(draft, 0, { ...TROOPERS, unit_type: "gone" }, [3, 3]);
    expect(fitsTemplate(view, gone)).toBe(false);
  });
});
