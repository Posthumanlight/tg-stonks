import { combatApi } from "../../net/api";
import type { CombatSummaryView } from "../../protocol";
import { combat } from "../../state/combat";
import { goTo } from "../../state/screen";

/** Leave the fight (unsubscribe, close the socket) and return to the lobby. */
export function backToLobby(): void {
  combat.leave();
  goTo("lobby");
}

/** Show a fight by id (just created, or resumed). */
export function openCombat(combatId: string): void {
  combat.open(combatId);
  goTo("combat");
}

/** The user's battles in progress (at most one hotseat and one online). Throws the
 * HTTP error. */
export async function listActiveCombats(): Promise<CombatSummaryView[]> {
  return (await combatApi.list()).filter((c) => c.status === "active");
}

/** The user's active hotseat fight, if any (one per user). Throws the HTTP error. */
export async function findActiveCombat(): Promise<CombatSummaryView | null> {
  return (await listActiveCombats()).find((c) => c.mode === "hotseat") ?? null;
}
