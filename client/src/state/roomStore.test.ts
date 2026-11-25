import { describe, expect, it, vi } from "vitest";

import { fakeTransport } from "../net/fakeTransport";
import type { RoomView } from "../protocol";
import { type RoomApi, type RoomTransport, createRoomStore } from "./roomStore";

const army = { faction: "concord", units: [{ unit_type: "warden", models: 1, origin: [0, 0] as [number, number] }] };

function roomView(overrides: Partial<RoomView> = {}): RoomView {
  return {
    room_id: "r1",
    code: "ABC123",
    name: "Duel",
    private: true,
    points_limit: 0,
    timer_s: 45,
    status: "full",
    host_user_id: 1,
    your_side: 1,
    players: [
      { user_id: 1, name: "ada", side: 0, ready: true, connected: true, faction: "concord", points: 440, unit_count: 4 },
      { user_id: 2, name: "bo", side: 1, ready: false, connected: true, faction: null, points: null, unit_count: null },
    ],
    your_army: null,
    ...overrides,
  };
}

function setup(api: Partial<RoomApi> = {}) {
  const fake = fakeTransport();
  const calls: RoomApi = {
    ready: vi.fn(async () => ({ combat_id: null })),
    unready: vi.fn(async () => {}),
    leave: vi.fn(async () => {}),
    kick: vi.fn(async () => {}),
    ...api,
  };
  const store = createRoomStore(fake.transport as RoomTransport, calls);
  store.open("r1");
  return { fake, store, api: calls };
}

describe("room store", () => {
  it("subscribes, and takes pushed state for its own room only", () => {
    const { fake, store } = setup();
    expect(fake.requests[0]).toEqual({ type: "room.subscribe", payload: { room_id: "r1" } });
    fake.push({ type: "room.state", payload: roomView({ room_id: "other" }) });
    expect(store.room.value).toBeNull();
    fake.push({ type: "room.state", payload: roomView() });
    expect(store.me.value?.name).toBe("bo");
    expect(store.opponent.value?.name).toBe("ada");
    expect(store.isHost.value).toBe(false);
    fake.welcome(); // a reconnect resubscribes
    expect(fake.requests.filter((r) => r.type === "room.subscribe")).toHaveLength(2);
  });

  it("hands over to the battle when it starts", async () => {
    const { fake, store, api } = setup({ ready: vi.fn(async () => ({ combat_id: "c9" })) });
    expect(await store.ready(army)).toBe("c9");
    expect(api.ready).toHaveBeenCalledWith("r1", army);
    expect(store.started.value).toBe("c9");
    store.detach(false);
    fake.push({ type: "room.started", payload: { room_id: "r1", combat_id: "c9" } });
    expect(store.started.value).toBeNull(); // detached: no longer ours
    expect(fake.raw.close).not.toHaveBeenCalled(); // the battle keeps the socket
  });

  it("closing sends the player back with the reason; leaving closes quietly", async () => {
    const { fake, store } = setup();
    fake.push({ type: "room.closed", payload: { room_id: "r1", reason: "room.closed.kicked" } });
    expect(store.closed.value).toBe("room.closed.kicked");
    expect(store.roomId.value).toBeNull();

    const other = setup();
    await other.store.leave();
    expect(other.api.leave).toHaveBeenCalledWith("r1");
    expect(other.store.closed.value).toBeNull();
    expect(other.fake.raw.close).toHaveBeenCalled();
  });

  it("refused actions throw to the caller", async () => {
    const { store } = setup({ ready: vi.fn(async () => Promise.reject(new Error("nope"))) });
    await expect(store.ready(army)).rejects.toThrow("nope");
    expect(store.busy.value).toBe(false);
  });
});
