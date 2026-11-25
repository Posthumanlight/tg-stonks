import { room } from "../../state/rooms";
import { goTo } from "../../state/screen";

/** Show a room the player has just created or joined (or is back to). */
export function enterRoom(roomId: string): void {
  room.open(roomId);
  goTo("room");
}
