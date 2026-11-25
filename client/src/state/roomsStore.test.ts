import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../net/http";
import type { RoomCard } from "../protocol";
import { createRoomsStore } from "./roomsStore";

const card = (room_id: string): RoomCard => ({ room_id, name: room_id, host_name: "ada", points_limit: 0, timer_s: 45 });

describe("room search", () => {
  it("searches with the filter, keeping only the latest answer", async () => {
    let release: (() => void) | undefined;
    const search = vi
      .fn()
      .mockImplementationOnce(() => new Promise((resolve) => (release = () => resolve({ rooms: [card("old")] }))))
      .mockResolvedValueOnce({ rooms: [card("new")] });
    const store = createRoomsStore({ search });
    const slow = store.refresh();
    store.setFilter({ query: " duel ", points: 500 });
    await vi.waitFor(() => expect(store.list.value.status).toBe("ready"));
    release?.();
    await slow;
    expect(store.list.value).toEqual({ status: "ready", rooms: [card("new")] });
    expect(search).toHaveBeenLastCalledWith("duel", 500);
  });

  it("reports a failed search", async () => {
    const store = createRoomsStore({ search: async () => Promise.reject(new ApiError(503, "combat.unavailable")) });
    await store.refresh();
    expect(store.list.value).toEqual({ status: "error", reason: "combat.unavailable" });
  });
});
