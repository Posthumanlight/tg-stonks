import { describe, expect, it } from "vitest";

import { unit } from "./fixtures";
import { formatEvent, outcomeText, sideLabel, unitLabel } from "./log";

const units = [unit({ uid: 1 }), unit({ uid: 2, side: 1, unit_type: "ravager_swarm" })];
const ev = (type: string, data: Record<string, unknown>, seq = 0) => ({ type, seq, data });

describe("formatEvent", () => {
  it("narrates an attack with content names", () => {
    const line = formatEvent(
      ev("attack_resolved", {
        attacker: 1,
        target: 2,
        weapon: "pulse_rifle",
        hits: 4,
        total_damage: 4,
        kills: 2,
      }),
      units,
    );
    expect(line).toBe(
      "Line Troopers #1 → Ravager Swarm #2 with Pulse rifle: 4 hits, 4 damage, 2 killed.",
    );
  });

  it("formats rounds, moves and the end of the fight", () => {
    expect(formatEvent(ev("round_started", { round: 3 }), units)).toBe("— Round 3 —");
    expect(formatEvent(ev("unit_moved", { unit: 1, to_square: [4, 5] }), units)).toBe(
      "Line Troopers #1 moves to 4,5.",
    );
    expect(formatEvent(ev("combat_ended", { winners: [1], draw: false }), units)).toBe(
      "Side 2 wins.",
    );
  });

  it("only logs declared attacks that are opportunity attacks", () => {
    expect(formatEvent(ev("attack_declared", { attacker: 2, target: 1, opportunity: false }), units))
      .toBeNull();
    expect(
      formatEvent(ev("attack_declared", { attacker: 2, target: 1, opportunity: true }), units),
    ).toBe("Ravager Swarm #2 strikes Line Troopers #1 as it leaves!");
  });

  it("skips bookkeeping events", () => {
    for (const type of ["rolled", "hit_resolved", "activation_ended", "model_killed"]) {
      expect(formatEvent(ev(type, {}), units)).toBeNull();
    }
  });

  it("translates hooked log messages with their params", () => {
    expect(
      formatEvent(ev("log_message", { key: "combat.round", params: [["round", "7"]] }), units),
    ).toBe("Round 7");
  });
});

describe("labels", () => {
  it("falls back to the uid for unknown units", () => {
    expect(unitLabel(units, 99)).toBe("#99");
  });

  it("calls a winnerless outcome a draw", () => {
    expect(outcomeText(false, [])).toBe("The battle ends in a draw.");
    expect(outcomeText(true, [0])).toBe("The battle ends in a draw.");
    expect(outcomeText(false, [0, 2])).toBe("Side 1, Side 3 wins.");
  });

  it("names sides by faction, numbering a mirror match", () => {
    expect(sideLabel(1, ["concord", "brood"])).toBe("Brood");
    expect(sideLabel(1, ["concord", "concord"])).toBe("Concord 2");
    expect(sideLabel(1, null)).toBe("Side 2");
    expect(outcomeText(false, [0], ["concord", "brood"])).toBe("Concord wins.");
  });
});
