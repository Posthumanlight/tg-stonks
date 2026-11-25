import { describe, expect, it } from "vitest";

import { legal, unit } from "./fixtures";
import {
  MOVE_MODE,
  covers,
  highlights,
  isSelfCast,
  keepMode,
  moveTo,
  squareAt,
  tapResult,
  unitAt,
  weaponChoices,
} from "./interaction";

const troopers = unit({ uid: 1, origin: [2, 2] });
const enemy = unit({ uid: 2, side: 1, origin: [6, 2] });
const walker = unit({ uid: 3, origin: [10, 10], size: 2 });
const dead = unit({ uid: 4, side: 1, origin: [4, 4], models: 0 });
const units = [troopers, enemy, walker, dead];

const options = legal({
  unit: 1,
  moves: [
    { to: [3, 2], cost: 1, provokes: [] },
    { to: [4, 4], cost: 3, provokes: [2] },
  ],
  attacks: [
    { weapon: "pulse_rifle", target: 2, ap_cost: 1, cover: false },
    { weapon: "sidearm", target: 2, ap_cost: 1, cover: true },
  ],
  abilities: [
    { ability: "frag_charge", ap_cost: 1, target_units: [], target_squares: [[7, 7]] },
    { ability: "fall_back", ap_cost: 1, target_units: [1], target_squares: [] },
  ],
});

describe("board geometry", () => {
  it("covers footprints and finds living units only", () => {
    expect(covers([10, 10], 2, [11, 11])).toBe(true);
    expect(covers([10, 10], 2, [12, 10])).toBe(false);
    expect(unitAt(units, [11, 10])?.uid).toBe(3);
    expect(unitAt(units, [4, 4])).toBeUndefined(); // dead units don't block taps
  });

  it("maps world points to squares, null off the board", () => {
    const board = { width: 24, height: 24 };
    expect(squareAt(board, 32, 70, 33)).toEqual([2, 1]);
    expect(squareAt(board, 32, -1, 0)).toBeNull();
    expect(squareAt(board, 32, 24 * 32, 0)).toBeNull();
  });
});

describe("highlights", () => {
  it("shows moves in move mode, targets in attack and ability modes", () => {
    expect(highlights(options, MOVE_MODE).moves).toHaveLength(2);
    expect(highlights(options, { kind: "attack", weapon: "sidearm" }).targetUnits).toEqual([2]);
    expect(highlights(options, { kind: "ability", ability: "frag_charge" }).targetSquares).toEqual([
      [7, 7],
    ]);
    expect(highlights(null, MOVE_MODE).moves).toEqual([]);
  });
});

describe("tapResult", () => {
  it("moves to a legal destination", () => {
    expect(tapResult([3, 2], options, MOVE_MODE, units)).toEqual({
      kind: "intent",
      intent: { type: "move", to: [3, 2] },
    });
  });

  it("inspects a unit in move mode, and does nothing on empty ground", () => {
    expect(tapResult([6, 2], options, MOVE_MODE, units)).toEqual({ kind: "inspect", unit: 2 });
    expect(tapResult([0, 20], options, MOVE_MODE, units)).toEqual({ kind: "none" });
  });

  it("attacks a listed target with the chosen weapon", () => {
    expect(tapResult([6, 2], options, { kind: "attack", weapon: "pulse_rifle" }, units)).toEqual({
      kind: "intent",
      intent: { type: "attack", weapon: "pulse_rifle", target: 2 },
    });
  });

  it("cancels attack mode on empty ground, inspects a non-target unit", () => {
    const mode = { kind: "attack", weapon: "pulse_rifle" } as const;
    expect(tapResult([0, 20], options, mode, units)).toEqual({ kind: "cancel" });
    expect(tapResult([2, 2], options, mode, units)).toEqual({ kind: "inspect", unit: 1 });
  });

  it("casts on a listed square or unit", () => {
    expect(tapResult([7, 7], options, { kind: "ability", ability: "frag_charge" }, units)).toEqual({
      kind: "intent",
      intent: { type: "ability", ability: "frag_charge", target_square: [7, 7] },
    });
    expect(tapResult([2, 2], options, { kind: "ability", ability: "fall_back" }, units)).toEqual({
      kind: "intent",
      intent: { type: "ability", ability: "fall_back", target_unit: 1 },
    });
  });

  it("only inspects when there is nothing legal (not this side's turn, or over)", () => {
    expect(tapResult([3, 2], null, MOVE_MODE, units)).toEqual({ kind: "none" });
    expect(tapResult([6, 2], null, MOVE_MODE, units)).toEqual({ kind: "inspect", unit: 2 });
  });
});

describe("moveTo for big units", () => {
  it("accepts a tap anywhere in the destination footprint, cheapest first", () => {
    const big = legal({
      unit: 3,
      moves: [
        { to: [12, 10], cost: 2, provokes: [] },
        { to: [11, 10], cost: 1, provokes: [] },
      ],
    });
    expect(moveTo(big, [12, 11], 2)?.to).toEqual([11, 10]);
    expect(moveTo(big, [12, 10], 2)?.to).toEqual([12, 10]); // exact origin wins
    expect(tapResult([12, 11], big, MOVE_MODE, units)).toEqual({
      kind: "intent",
      intent: { type: "move", to: [11, 10] },
    });
  });
});

describe("action choices", () => {
  it("lists each weapon once with its target count", () => {
    expect(weaponChoices(options)).toEqual([
      { weapon: "pulse_rifle", apCost: 1, targets: 1 },
      { weapon: "sidearm", apCost: 1, targets: 1 },
    ]);
    expect(weaponChoices(null)).toEqual([]);
  });

  it("recognises self-cast abilities", () => {
    expect(isSelfCast(options.abilities[1]!, 1)).toBe(true);
    expect(isSelfCast(options.abilities[0]!, 1)).toBe(false);
  });

  it("drops back to move mode when the chosen option is gone", () => {
    const mode = { kind: "attack", weapon: "pulse_rifle" } as const;
    expect(keepMode(mode, options)).toBe(mode);
    expect(keepMode(mode, legal())).toEqual(MOVE_MODE);
    expect(keepMode({ kind: "ability", ability: "nope" }, options)).toEqual(MOVE_MODE);
    expect(keepMode(MOVE_MODE, null)).toEqual(MOVE_MODE);
  });
});
