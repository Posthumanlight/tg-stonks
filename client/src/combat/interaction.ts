// Pure combat-screen interaction (no Phaser, no signals): what a tap means and what to
// highlight, given the server's `legal` options. The client never judges legality itself
// (CLAUDE.md rule 1): every choice here is picked from what the server listed.
import type {
  AbilityIntent,
  AbilityOptionView,
  AttackIntent,
  CombatLegal,
  MoveIntent,
  MoveOptionView,
  SkipIntent,
  UnitView,
  WaitIntent,
} from "../protocol";

export type Square = readonly [number, number];
export type Intent = MoveIntent | AttackIntent | AbilityIntent | WaitIntent | SkipIntent;

/** What a tap on the board does: move (default), fire a chosen weapon, cast an ability. */
export type Mode =
  | { readonly kind: "move" }
  | { readonly kind: "attack"; readonly weapon: string }
  | { readonly kind: "ability"; readonly ability: string };

export const MOVE_MODE: Mode = { kind: "move" };

export type TapResult =
  | { readonly kind: "intent"; readonly intent: Intent }
  | { readonly kind: "inspect"; readonly unit: number }
  | { readonly kind: "cancel" } // leave attack/ability mode
  | { readonly kind: "none" };

export const sameSquare = (a: Square, b: Square): boolean => a[0] === b[0] && a[1] === b[1];

export const isAlive = (unit: UnitView): boolean => unit.models > 0;

/** Whether a unit of `size` placed at `origin` covers `square`. */
export function covers(origin: Square, size: number, [x, y]: Square): boolean {
  return x >= origin[0] && x < origin[0] + size && y >= origin[1] && y < origin[1] + size;
}

/** Board square under a world point (`tile` world units per square), or null off-board. */
export function squareAt(
  board: { readonly width: number; readonly height: number },
  tile: number,
  x: number,
  y: number,
): Square | null {
  const sx = Math.floor(x / tile);
  const sy = Math.floor(y / tile);
  return sx >= 0 && sy >= 0 && sx < board.width && sy < board.height ? [sx, sy] : null;
}

/** The living unit standing on `square`, if any. */
export function unitAt(units: readonly UnitView[], square: Square): UnitView | undefined {
  return units.find((u) => isAlive(u) && covers(u.origin, u.size, square));
}

export interface Highlights {
  readonly moves: readonly MoveOptionView[];
  readonly targetUnits: readonly number[];
  readonly targetSquares: readonly Square[];
}

const NO_HIGHLIGHTS: Highlights = { moves: [], targetUnits: [], targetSquares: [] };

function abilityOption(legal: CombatLegal, ability: string): AbilityOptionView | undefined {
  return legal.abilities.find((a) => a.ability === ability);
}

export function highlights(legal: CombatLegal | null, mode: Mode): Highlights {
  if (!legal) return NO_HIGHLIGHTS;
  switch (mode.kind) {
    case "move":
      return { ...NO_HIGHLIGHTS, moves: legal.moves };
    case "attack":
      return {
        ...NO_HIGHLIGHTS,
        targetUnits: legal.attacks.filter((a) => a.weapon === mode.weapon).map((a) => a.target),
      };
    case "ability": {
      const option = abilityOption(legal, mode.ability);
      return option
        ? { moves: [], targetUnits: option.target_units, targetSquares: option.target_squares }
        : NO_HIGHLIGHTS;
    }
  }
}

/** The move whose destination is `square`; for big units, the cheapest one covering it. */
export function moveTo(
  legal: CombatLegal,
  square: Square,
  size: number,
): MoveOptionView | undefined {
  const exact = legal.moves.find((m) => sameSquare(m.to, square));
  if (exact || size <= 1) return exact;
  let best: MoveOptionView | undefined;
  for (const move of legal.moves) {
    if (covers(move.to, size, square) && (!best || move.cost < best.cost)) best = move;
  }
  return best;
}

export function tapResult(
  square: Square,
  legal: CombatLegal | null,
  mode: Mode,
  units: readonly UnitView[],
): TapResult {
  const unit = unitAt(units, square);
  if (legal) {
    switch (mode.kind) {
      case "move": {
        const size = units.find((u) => u.uid === legal.unit)?.size ?? 1;
        const move = moveTo(legal, square, size);
        if (move && (!unit || unit.uid === legal.unit)) {
          return { kind: "intent", intent: { type: "move", to: [move.to[0], move.to[1]] } };
        }
        break;
      }
      case "attack":
        if (unit && legal.attacks.some((a) => a.weapon === mode.weapon && a.target === unit.uid)) {
          return {
            kind: "intent",
            intent: { type: "attack", weapon: mode.weapon, target: unit.uid },
          };
        }
        return unit ? { kind: "inspect", unit: unit.uid } : { kind: "cancel" };
      case "ability": {
        const option = abilityOption(legal, mode.ability);
        if (option && unit && option.target_units.includes(unit.uid)) {
          return {
            kind: "intent",
            intent: { type: "ability", ability: mode.ability, target_unit: unit.uid },
          };
        }
        if (option?.target_squares.some((s) => sameSquare(s, square))) {
          return {
            kind: "intent",
            intent: { type: "ability", ability: mode.ability, target_square: [square[0], square[1]] },
          };
        }
        return unit ? { kind: "inspect", unit: unit.uid } : { kind: "cancel" };
      }
    }
  }
  return unit ? { kind: "inspect", unit: unit.uid } : { kind: "none" };
}

export interface WeaponChoice {
  readonly weapon: string;
  readonly apCost: number;
  readonly targets: number;
}

/** One entry per weapon that has at least one legal target, in server order. */
export function weaponChoices(legal: CombatLegal | null): WeaponChoice[] {
  const byWeapon = new Map<string, WeaponChoice>();
  for (const attack of legal?.attacks ?? []) {
    const seen = byWeapon.get(attack.weapon);
    byWeapon.set(attack.weapon, {
      weapon: attack.weapon,
      apCost: attack.ap_cost,
      targets: (seen?.targets ?? 0) + 1,
    });
  }
  return [...byWeapon.values()];
}

/** A self-targeted ability needs no board tap: the button casts it directly. */
export function isSelfCast(option: AbilityOptionView, caster: number): boolean {
  return (
    option.target_squares.length === 0 &&
    option.target_units.length === 1 &&
    option.target_units[0] === caster
  );
}

/** The mode to keep after `legal` changed: back to move if its choice is gone. */
export function keepMode(mode: Mode, legal: CombatLegal | null): Mode {
  if (!legal) return MOVE_MODE;
  switch (mode.kind) {
    case "move":
      return mode;
    case "attack":
      return legal.attacks.some((a) => a.weapon === mode.weapon) ? mode : MOVE_MODE;
    case "ability":
      return abilityOption(legal, mode.ability) ? mode : MOVE_MODE;
  }
}
