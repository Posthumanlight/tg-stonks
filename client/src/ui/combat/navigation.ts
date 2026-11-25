import { combat } from "../../state/combat";
import { goTo } from "../../state/screen";

/** Leave the fight (unsubscribe, close the socket) and return to the lobby. */
export function backToLobby(): void {
  combat.leave();
  goTo("lobby");
}
