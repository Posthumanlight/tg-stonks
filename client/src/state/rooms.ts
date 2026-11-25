// Wiring: the app's room and room-search stores over the real API and the one
// WebSocket (the logic is in roomStore.ts and roomsStore.ts).
import { roomsApi } from "../net/api";
import { socket } from "./combat";
import { createRoomStore } from "./roomStore";
import { createRoomsStore } from "./roomsStore";

export const room = createRoomStore(socket, roomsApi);
export const rooms = createRoomsStore(roomsApi);
