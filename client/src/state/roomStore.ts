// The lobby room the player is in (docs/client.md "Lobby rooms"), fed by WebSocket
// pushes: `room.state` replaces the view wholesale, `room.started` hands over to the
// battle, `room.closed` ends it. Changes go over HTTP (roomsApi). A factory over an
// injected transport and API, so tests drive it without a server; state/rooms.ts wires
// the real ones.
import { batch, computed, signal } from "@preact/signals";

import type { WsClient } from "../net/ws";
import type { RoomPlayer, RoomReady, RoomView, SideSetup } from "../protocol";

export type RoomTransport = Pick<WsClient, "connect" | "close" | "request" | "on" | "onWelcome" | "status">;

export interface RoomApi {
  ready(roomId: string, side: SideSetup): Promise<RoomReady>;
  unready(roomId: string): Promise<void>;
  leave(roomId: string): Promise<void>;
  kick(roomId: string): Promise<void>;
}

export function createRoomStore(transport: RoomTransport, api: RoomApi) {
  const roomId = signal<string | null>(null);
  const room = signal<RoomView | null>(null);
  /** Why the room ended for this player (a `room.closed.*` key); the lobby shows it. */
  const closed = signal<string | null>(null);
  /** The battle the room started; the screen opens it. */
  const started = signal<string | null>(null);
  const busy = signal(false);

  const me = computed<RoomPlayer | null>(() => {
    const view = room.value;
    return view?.players.find((p) => p.side === view.your_side) ?? null;
  });
  const opponent = computed<RoomPlayer | null>(() => {
    const view = room.value;
    return view?.players.find((p) => p.side !== view.your_side) ?? null;
  });
  const isHost = computed(() => {
    const view = room.value;
    return view !== null && me.value?.user_id === view.host_user_id;
  });

  const ours = (id: string): boolean => id === roomId.peek();

  async function subscribe(): Promise<void> {
    const id = roomId.peek();
    if (!id) return;
    try {
      await transport.request("room.subscribe", { room_id: id });
    } catch (error) {
      // Gone while we were away (closed, or we were dropped): back to the lobby.
      if (ours(id) && room.peek() === null) closed.value = "room.closed.gone";
      void error;
    }
  }

  transport.on("room.state", (message) => {
    if (ours(message.payload.room_id)) room.value = message.payload;
  });
  transport.on("room.started", (message) => {
    if (ours(message.payload.room_id)) started.value = message.payload.combat_id;
  });
  transport.on("room.closed", (message) => {
    if (!ours(message.payload.room_id)) return;
    batch(() => {
      closed.value = message.payload.reason;
      room.value = null;
      roomId.value = null;
    });
  });
  transport.onWelcome(() => void subscribe()); // every (re)connect resubscribes

  /** Watch a room the player has just created or joined. */
  function open(id: string): void {
    batch(() => {
      roomId.value = id;
      room.value = null;
      closed.value = null;
      started.value = null;
    });
    if (transport.status === "open") void subscribe();
    else transport.connect();
  }

  /** Stop watching (the screen changed). `closeSocket` unless a battle takes over. */
  function detach(closeSocket: boolean): void {
    const id = roomId.peek();
    if (id && transport.status === "open") {
      transport.request("room.unsubscribe", { room_id: id }).catch(() => {});
    }
    batch(() => {
      roomId.value = null;
      room.value = null;
      started.value = null;
    });
    if (closeSocket) transport.close();
  }

  async function run<T>(action: (id: string) => Promise<T>): Promise<T | null> {
    const id = roomId.peek();
    if (!id || busy.peek()) return null;
    busy.value = true;
    try {
      return await action(id);
    } finally {
      busy.value = false;
    }
  }

  /** Lock in the army. Throws the HTTP error (the builder shows located issues). */
  async function ready(side: SideSetup): Promise<string | null> {
    const result = await run((id) => api.ready(id, side));
    const combatId = result?.combat_id ?? null;
    if (combatId) started.value = combatId;
    return combatId;
  }

  const unready = (): Promise<void | null> => run((id) => api.unready(id));
  const kick = (): Promise<void | null> => run((id) => api.kick(id));

  async function leave(): Promise<void> {
    await run((id) => api.leave(id));
    closed.value = null; // our own choice: nothing to explain
    detach(true);
  }

  function clearClosed(): void {
    closed.value = null;
  }

  return {
    roomId,
    room,
    closed,
    started,
    busy,
    me,
    opponent,
    isHost,
    open,
    detach,
    ready,
    unready,
    kick,
    leave,
    clearClosed,
  };
}

export type RoomStore = ReturnType<typeof createRoomStore>;
