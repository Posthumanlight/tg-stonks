import { describe, expect, it } from "vitest";

import { IDLE, begin, carried, hover, pick, release } from "./drag";

const token = { kind: "token", ref: { side: 0, index: 1 } } as const;
const roster = { kind: "roster", unitType: "warden" } as const;

describe("drag state machine", () => {
  it("places a roster card dropped on a square", () => {
    const over = hover(begin(roster), [2, 3]);
    expect(over).toEqual({ phase: "dragging", source: roster, over: [2, 3] });
    expect(release(over, { kind: "square", square: [2, 3] })).toEqual({
      state: IDLE,
      command: { type: "place", unitType: "warden", at: [2, 3] },
    });
  });

  it("moves a token, removes it on the tray, cancels off the board", () => {
    const dragging = begin(token);
    expect(release(dragging, { kind: "square", square: [4, 4] }).command).toEqual({
      type: "move",
      ref: token.ref,
      to: [4, 4],
    });
    expect(release(dragging, { kind: "tray" }).command).toEqual({ type: "remove", ref: token.ref });
    expect(release(dragging, { kind: "none" })).toEqual({ state: IDLE, command: null });
    expect(release(begin(roster), { kind: "tray" }).command).toBeNull(); // nothing to remove
  });

  it("tap fallback: picked up, then dropped by a tap", () => {
    const picked = pick(roster);
    expect(picked.phase).toBe("picked");
    expect(carried(picked)).toBe(roster);
    expect(release(picked, { kind: "square", square: [1, 1] }).command).toMatchObject({ type: "place" });
  });

  it("ignores hovers while idle and keeps the state for the same square", () => {
    expect(hover(IDLE, [1, 1])).toBe(IDLE);
    const over = hover(begin(token), [1, 1]);
    expect(hover(over, [1, 1])).toBe(over);
    expect(release(IDLE, { kind: "square", square: [0, 0] })).toEqual({ state: IDLE, command: null });
  });
});
