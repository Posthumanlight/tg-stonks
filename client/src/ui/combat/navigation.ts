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

/** The user's active hotseat fight, if any (one per user). Throws the HTTP error. */
export async function findActiveCombat(): Promise<CombatSummaryView | null> {
  const combats = await combatApi.list();
  return combats.find((c) => c.status === "active") ?? null;
}
