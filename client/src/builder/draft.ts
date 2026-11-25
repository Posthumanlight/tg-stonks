// The custom-battle draft: both armies as the player is building them. It has the exact
// shape of the request (CustomCombatRequest), so Start sends it as is. Pure functions
// only; the store (state/builderStore.ts) holds the signals.
import type {
  BuilderView,
  CustomCombatRequest,
  DeployedUnit,
  FactionCard,
  SideSetup,
  UnitCard,
} from "../protocol";
import { type Square, footprint, placementIssue, squareKey, zoneFor } from "./placement";

export type Draft = CustomCombatRequest;

/** Which unit: its side and its index in that side's units. */
export interface UnitRef {
  readonly side: number;
  readonly index: number;
}

/** A problem to fix before Start: side-wide (`unit` null) or one unit's. */
export interface Issue {
  readonly side: number;
  readonly unit: number | null;
  readonly reason: string;
}

export const sameRef = (a: UnitRef | null, b: UnitRef | null): boolean =>
  a !== null && b !== null && a.side === b.side && a.index === b.index;

export function factionCard(template: BuilderView, faction: string): FactionCard | undefined {
  return template.factions.find((f) => f.id === faction);
}

export function unitCard(template: BuilderView, unitType: string): UnitCard | undefined {
  for (const faction of template.factions) {
    const card = faction.units.find((u) => u.unit_type === unitType);
    if (card) return card;
  }
  return undefined;
}

function withSide(draft: Draft, side: number, change: (s: SideSetup) => SideSetup): Draft {
  const [a, b] = draft.sides;
  return { sides: side === 0 ? [change(a), b] : [a, change(b)] };
}

function withUnits(
  draft: Draft,
  side: number,
  change: (units: DeployedUnit[]) => DeployedUnit[],
): Draft {
  return withSide(draft, side, (s) => ({ ...s, units: change(s.units) }));
}

export function placeUnit(draft: Draft, side: number, card: UnitCard, at: Square): Draft {
  const unit: DeployedUnit = { unit_type: card.unit_type, models: card.models.default, origin: [at[0], at[1]] };
  return withUnits(draft, side, (units) => [...units, unit]);
}

export function moveUnit(draft: Draft, ref: UnitRef, to: Square): Draft {
  return withUnits(draft, ref.side, (units) =>
    units.map((u, i) => (i === ref.index ? { ...u, origin: [to[0], to[1]] } : u)),
  );
}

export function removeUnit(draft: Draft, ref: UnitRef): Draft {
  return withUnits(draft, ref.side, (units) => units.filter((_, i) => i !== ref.index));
}

export function setModels(draft: Draft, ref: UnitRef, card: UnitCard, models: number): Draft {
  const clamped = Math.min(card.models.max, Math.max(card.models.min, Math.round(models)));
  return withUnits(draft, ref.side, (units) =>
    units.map((u, i) => (i === ref.index ? { ...u, models: clamped } : u)),
  );
}

/** A new faction empties the side: its units belong to the old one. */
export function setFaction(draft: Draft, side: number, faction: string): Draft {
  return withSide(draft, side, () => ({ faction, units: [] }));
}

export function getUnit(draft: Draft, ref: UnitRef): DeployedUnit | undefined {
  return draft.sides[ref.side]?.units[ref.index];
}

/** Display-only points: a unit's points don't scale with its size in v1. */
export function sidePoints(template: BuilderView, side: SideSetup): number {
  return side.units.reduce((sum, u) => sum + (unitCard(template, u.unit_type)?.points ?? 0), 0);
}

/** The unit standing on `square` (any side), if any. */
export function unitAtSquare(template: BuilderView, draft: Draft, square: Square): UnitRef | null {
  const key = squareKey(square);
  for (const [side, setup] of draft.sides.entries()) {
    for (const [index, unit] of setup.units.entries()) {
      const size = unitCard(template, unit.unit_type)?.footprint ?? 1;
      if (footprint(unit.origin, size).some((s) => squareKey(s) === key)) return { side, index };
    }
  }
  return null;
}

/** Squares taken by every unit except `skip` (the one being moved). */
export function occupied(template: BuilderView, draft: Draft, skip: UnitRef | null = null): Set<string> {
  const taken = new Set<string>();
  draft.sides.forEach((setup, side) =>
    setup.units.forEach((unit, index) => {
      if (sameRef(skip, { side, index })) return;
      const size = unitCard(template, unit.unit_type)?.footprint ?? 1;
      for (const s of footprint(unit.origin, size)) taken.add(squareKey(s));
    }),
  );
  return taken;
}

/** terrain id -> passable, from the template. */
export function passableTerrain(template: BuilderView): Record<string, boolean> {
  return Object.fromEntries(
    Object.entries(template.terrain).map(([id, card]) => [id, card?.passable ?? false]),
  );
}

/** Why a footprint can't go to `at` for `side` (ignoring `moving` itself), or null. */
export function dropIssue(
  template: BuilderView,
  draft: Draft,
  side: number,
  size: number,
  at: Square,
  moving: UnitRef | null = null,
): string | null {
  const passable = passableTerrain(template);
  return placementIssue(
    template.board,
    passable,
    at,
    size,
    occupied(template, draft, moving),
    zoneFor(template.zones, side),
  );
}

/** Which of the draft's sides are checked, and the room's points limit (online rooms
 * check only the player's own side; 0 or absent = no limit). */
export interface IssueScope {
  readonly sides?: readonly number[];
  readonly pointsLimit?: number;
}

/** Everything the server would reject, in its order: side-wide checks, then each unit
 * in setup order (side 0's units, then side 1's) against the units placed before it. */
export function draftIssues(template: BuilderView, draft: Draft, scope: IssueScope = {}): Issue[] {
  const issues: Issue[] = [];
  const limit = template.limits.max_units_per_side;
  const checked = (side: number) => !scope.sides || scope.sides.includes(side);
  draft.sides.forEach((setup, side) => {
    if (!checked(side)) return;
    if (!factionCard(template, setup.faction)) issues.push({ side, unit: null, reason: "setup.unknown_faction" });
    if (setup.units.length === 0) issues.push({ side, unit: null, reason: "setup.empty_side" });
    if (setup.units.length > limit) issues.push({ side, unit: null, reason: "setup.too_many_units" });
  });
  const passable = passableTerrain(template);
  const taken = new Set<string>();
  draft.sides.forEach((setup, side) =>
    setup.units.forEach((unit, index) => {
      const card = unitCard(template, unit.unit_type);
      const size = card?.footprint ?? 1;
      const reason = unitIssue(template, setup, unit, card) ??
        placementIssue(template.board, passable, unit.origin, size, taken, zoneFor(template.zones, side));
      if (reason && checked(side)) issues.push({ side, unit: index, reason });
      for (const s of footprint(unit.origin, size)) taken.add(squareKey(s));
    }),
  );
  if (scope.pointsLimit) {
    draft.sides.forEach((setup, side) => {
      if (checked(side) && sidePoints(template, setup) > (scope.pointsLimit ?? 0)) {
        issues.push({ side, unit: null, reason: "setup.over_points" });
      }
    });
  }
  return issues;
}

function unitIssue(
  template: BuilderView,
  setup: SideSetup,
  unit: DeployedUnit,
  card: UnitCard | undefined,
): string | null {
  if (!card) return "setup.unknown_unit";
  if (!factionCard(template, setup.faction)?.units.includes(card)) return "setup.wrong_faction";
  if (unit.models < card.models.min || unit.models > card.models.max) return "setup.models_out_of_range";
  return null;
}

/** Can a saved draft still be used with this template? (Content may have changed.) */
export function fitsTemplate(template: BuilderView, draft: unknown): draft is Draft {
  if (!draft || typeof draft !== "object" || !("sides" in draft)) return false;
  const sides = (draft as Draft).sides;
  if (!Array.isArray(sides) || sides.length !== 2) return false;
  return sides.every(
    (setup) =>
      Array.isArray(setup?.units) &&
      setup.units.every(
        (u) =>
          Array.isArray(u?.origin) &&
          u.origin.length === 2 &&
          typeof u.models === "number" &&
          unitIssue(template, setup, u, unitCard(template, u.unit_type)) === null,
      ) &&
      factionCard(template, setup.faction) !== undefined,
  );
}
