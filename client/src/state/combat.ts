// Wiring: the app's one WebSocket and combat store (the logic is in combatStore.ts).
import { combatApi } from "../net/api";
import { WsClient, defaultWsUrl } from "../net/ws";
import { currentUser, getAccessToken, onTokenChange, refreshSession } from "./auth";
import { createCombatStore } from "./combatStore";

export const socket = new WsClient({
  url: defaultWsUrl(window.location),
  token: getAccessToken,
  refresh: refreshSession,
});
onTokenChange((token) => socket.updateToken(token));

export const combat = createCombatStore(socket, combatApi, () => currentUser.value?.user_id ?? null);
