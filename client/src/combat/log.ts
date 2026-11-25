// Combat events -> human log lines. Pure apart from the current locale (tKey).
// Noisy bookkeeping events (dice, single hits, activation ends…) are left out: the log
// shows what a player would narrate, the canvas shows the rest.
import { tKey } from "../i18n";
import type { CombatEvent, UnitView } from "../protocol";

/** Display name of a unit: content name + uid, so two squads of one type differ. */
export function unitLabel(units: readonly UnitView[], uid: unknown): string {
  const unit = units.find((u) => u.uid === uid);
  return unit ? `${tKey(`unit.${unit.unit_type}.name`)} #${unit.uid}` : `#${String(uid)}`;
}

/** "Side 1" for side 0: sides are 0-based on the wire, 1-based for people. */
export const sideLabel = (side: number): string => tKey("combat.side", { n: side + 1 });

const square = (value: unknown): string =>
  Array.isArray(value) ? `${String(value[0])},${String(value[1])}` : "?";

const num = (value: unknown): number => (typeof value === "number" ? value : 0);

/** One log line for `event`, or null when the event isn't worth a line. */
export function formatEvent(event: CombatEvent, units: readonly UnitView[]): string | null {
  const d = event.data;
  const unit = (key: string) => unitLabel(units, d[key]);
  switch (event.type) {
    case "round_started":
      return tKey("combat.log.round", { round: num(d["round"]) });
    case "activation_started":
      return tKey("combat.log.turn", { unit: unit("unit") });
    case "unit_moved":
      return tKey("combat.log.moved", { unit: unit("unit"), to: square(d["to_square"]) });
    case "unit_repositioned":
      return tKey("combat.log.repositioned", { unit: unit("unit"), to: square(d["to_square"]) });
    case "unit_waited":
      return tKey("combat.log.waited", { unit: unit("unit") });
    case "attack_declared":
      return d["opportunity"]
        ? tKey("combat.log.opportunity", { attacker: unit("attacker"), target: unit("target") })
        : null;
    case "attack_resolved":
      return tKey("combat.log.attack", {
        attacker: unit("attacker"),
        target: unit("target"),
        weapon: tKey(`weapon.${String(d["weapon"])}.name`),
        hits: num(d["hits"]),
        damage: num(d["total_damage"]),
        kills: num(d["kills"]),
      });
    case "unit_destroyed":
      return tKey("combat.log.destroyed", { unit: unit("unit") });
    case "ability_used":
      return tKey("combat.log.ability", {
        unit: unit("unit"),
        ability: tKey(`ability.${String(d["ability"])}.name`),
      });
    case "status_applied":
      return tKey("combat.log.status", {
        unit: unit("unit"),
        status: tKey(`ability.${String(d["status"])}.name`),
      });
    case "healed":
      return tKey("combat.log.healed", { unit: unit("unit"), amount: num(d["amount"]) });
    case "models_revived":
      return tKey("combat.log.revived", { unit: unit("unit"), count: num(d["count"]) });
    case "unit_spawned":
      return tKey("combat.log.spawned", { unit: unit("unit") });
    case "log_message": {
      const params = Object.fromEntries(
        Array.isArray(d["params"]) ? (d["params"] as [string, string][]) : [],
      );
      return tKey(String(d["key"]), params);
    }
    case "hook_error":
      return tKey("combat.log.hook_error", {
        ability: tKey(`ability.${String(d["ability"])}.name`),
      });
    case "combat_ended":
      return outcomeText(Boolean(d["draw"]), (d["winners"] as number[] | undefined) ?? []);
    default:
      return null;
  }
}

/** "Side 2 wins." / "Draw." — shared by the log and the outcome dialog. */
export function outcomeText(draw: boolean, winners: readonly number[]): string {
  if (draw || winners.length === 0) return tKey("combat.outcome.draw");
  return tKey("combat.outcome.winners", { sides: winners.map(sideLabel).join(", ") });
}
