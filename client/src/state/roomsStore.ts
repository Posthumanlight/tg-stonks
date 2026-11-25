// Finding rooms (docs/client.md "Lobby rooms"): the search query, the points filter and
// the open public rooms. The screen refreshes it on a timer while it is shown.
import { batch, signal } from "@preact/signals";

import { ApiError } from "../net/http";
import type { RoomCard, RoomList } from "../protocol";

export interface RoomsSearchApi {
  search(query: string, points: number | null): Promise<RoomList>;
}

export type RoomsState =
  | { readonly status: "idle" | "loading" }
  | { readonly status: "error"; readonly reason: string }
  | { readonly status: "ready"; readonly rooms: readonly RoomCard[] };

export const REFRESH_MS = 5000;

export function createRoomsStore(api: RoomsSearchApi) {
  const query = signal("");
  /** null: any points limit. */
  const points = signal<number | null>(null);
  const list = signal<RoomsState>({ status: "idle" });
  let latest = 0; // answers to older searches are dropped

  async function refresh(): Promise<void> {
    const ticket = ++latest;
    if (list.peek().status !== "ready") list.value = { status: "loading" };
    try {
      const { rooms } = await api.search(query.peek().trim(), points.peek());
      if (ticket === latest) list.value = { status: "ready", rooms };
    } catch (error) {
      if (ticket === latest) {
        list.value = { status: "error", reason: error instanceof ApiError ? error.reasonKey : "error.generic" };
      }
    }
  }

  function setFilter(next: { query?: string; points?: number | null }): void {
    batch(() => {
      if (next.query !== undefined) query.value = next.query;
      if (next.points !== undefined) points.value = next.points;
    });
    void refresh();
  }

  return { query, points, list, refresh, setFilter };
}

export type RoomsStore = ReturnType<typeof createRoomsStore>;
