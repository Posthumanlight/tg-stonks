import { describe, expect, it, vi } from "vitest";

import { legal, view } from "../combat/fixtures";
import { fakeTransport } from "../net/fakeTransport";
import { type ConnectionStatus, WsError } from "../net/ws";
import type { CombatEvent } from "../protocol";
import { type CombatTransport, createCombatStore } from "./combatStore";

const board = { width: 24, height: 24, terrain: [] };
const events = (from: number, to: number): CombatEvent[] =>
  Array.from({ length: to - from }, (_, i) => ({ seq: from + i, type: "unit_waited", data: { unit: 1 } }));

async function opened(status: ConnectionStatus = "open") {
  const fake = fakeTransport(status);
  const store = createCombatStore(fake.transport as CombatTransport, { createDemo: async () => ({ combat_id: "c1" }) });
  await store.openDemo();
  store.applySnapshot({ board, view: view({ seq: 10 }), legal: legal() });
  return { fake, store };
}

describe("opening a fight", () => {
  it("subscribes right away when the socket is already open", async () => {
    const { fake, store } = await opened("open");
    expect(store.combatId.value).toBe("c1");
    expect(fake.requests[0]).toEqual({
      type: "combat.subscribe",
      payload: { combat_id: "c1", last_seq: null },
    });
  });

  it("connects first otherwise, and subscribes on welcome with the last seq", async () => {
    const { fake, store } = await opened("idle");
    expect(fake.raw.connect).toHaveBeenCalledOnce();
    expect(fake.requests).toEqual([]);
    fake.welcome();
    expect(fake.requests[0]?.payload).toEqual({ combat_id: "c1", last_seq: 10 });
    expect(store.view.value?.seq).toBe(10);
  });

  it("ignores snapshots of other combats", async () => {
    const { store } = await opened();
    store.applySnapshot({ board, view: view({ combat_id: "other", seq: 99 }), legal: null });
    expect(store.view.value?.seq).toBe(10);
  });
});

describe("applying updates", () => {
  const update = (from: number, to: number) => ({
    combat_id: "c1",
    from_seq: from,
    events: events(from, to),
    view: view({ seq: to, round: 2 }),
    legal: legal({ can_wait: false }),
  });

  it("replaces the view and legal, and appends events to the log", async () => {
    const { store } = await opened();
    store.applyUpdate(update(10, 13));
    expect(store.view.value?.round).toBe(2);
    expect(store.legal.value?.can_wait).toBe(false);
    expect(store.log.value.map((e) => e.seq)).toEqual([10, 11, 12]);
  });

  it("ignores duplicates and trims overlapping catch-ups", async () => {
    const { store } = await opened();
    store.applyUpdate(update(10, 13));
    store.applyUpdate(update(10, 13));
    store.applyUpdate(update(11, 15));
    expect(store.log.value.map((e) => e.seq)).toEqual([10, 11, 12, 13, 14]);
  });

  it("resubscribes from its last seq when it detects a gap", async () => {
    const { fake, store } = await opened();
    fake.requests.length = 0;
    store.applyUpdate(update(12, 14));
    expect(store.view.value?.seq).toBe(10);
    expect(fake.requests[0]).toEqual({
      type: "combat.subscribe",
      payload: { combat_id: "c1", last_seq: 10 },
    });
  });

  it("is driven by pushes from the transport", async () => {
    const { fake, store } = await opened();
    fake.push({ type: "combat.events", payload: update(10, 11) });
    expect(store.view.value?.seq).toBe(11);
  });
});

describe("acting", () => {
  it("sends taps on legal squares as intents", async () => {
    const { fake, store } = await opened();
    store.applySnapshot({
      board,
      view: view({ seq: 10 }),
      legal: legal({ moves: [{ to: [3, 2], cost: 1, provokes: [] }] }),
    });
    store.tap([3, 2]);
    expect(fake.requests.at(-1)).toEqual({
      type: "combat.action",
      payload: { combat_id: "c1", intent: { type: "move", to: [3, 2] } },
    });
  });

  it("shows the server's reason when an action is refused", async () => {
    const { fake, store } = await opened();
    fake.answerWith(async () => {
      throw new WsError("wait.forbidden");
    });
    await store.act({ type: "wait" });
    expect(store.lastError.value).toBe("wait.forbidden");
    expect(store.busy.value).toBe(false);
  });

  it("casts self abilities directly and toggles targeting for others", async () => {
    const { fake, store } = await opened();
    const self = { ability: "fall_back", ap_cost: 1, target_units: [1], target_squares: [] };
    const area = { ability: "frag_charge", ap_cost: 1, target_units: [], target_squares: [[7, 7]] as [number, number][] };
    store.applySnapshot({ board, view: view({ seq: 10 }), legal: legal({ abilities: [self, area] }) });

    store.chooseAbility(self);
    expect(fake.requests.at(-1)?.payload).toMatchObject({ intent: { type: "ability", ability: "fall_back" } });

    store.chooseAbility(area);
    expect(store.mode.value).toEqual({ kind: "ability", ability: "frag_charge" });
    store.chooseAbility(area);
    expect(store.mode.value).toEqual({ kind: "move" });
  });

  it("leave() unsubscribes, clears state and closes the socket", async () => {
    const { fake, store } = await opened();
    store.leave();
    expect(fake.requests.at(-1)).toEqual({ type: "combat.unsubscribe", payload: { combat_id: "c1" } });
    expect(fake.raw.close).toHaveBeenCalledOnce();
    expect(store.combatId.value).toBeNull();
    expect(store.view.value).toBeNull();
  });
});

describe("online battles", () => {
  const players = [
    { side: 0, user_id: 1, name: "ada" },
    { side: 1, user_id: 2, name: "bo" },
  ];
  const move = { to: [3, 2] as [number, number], cost: 1, provokes: [] };

  function online(me: number) {
    const fake = fakeTransport();
    const store = createCombatStore(
      fake.transport as CombatTransport,
      { createDemo: async () => ({ combat_id: "c1" }) },
      () => me,
    );
    store.open("c1");
    store.applySnapshot({
      board: { ...board, players },
      view: view(), // unit 1 (side 0) is active
      legal: legal({ moves: [move] }),
      deadline_ms: 1_000_000,
    });
    return { fake, store };
  }

  it("acts and highlights only on the player's own side's turn", () => {
    const waiting = online(2).store; // holds side 1
    expect(waiting.online.value).toBe(true);
    expect(waiting.myTurn.value).toBe(false);
    expect(waiting.marks.value.moves).toEqual([]);
    expect(waiting.sideNames.value).toEqual(["ada", "bo"]);
    expect(waiting.deadline.value).toBe(1_000_000);

    const { fake, store } = online(1); // holds side 0: its turn
    expect(store.myTurn.value).toBe(true);
    expect(store.marks.value.moves).toEqual([move]);
    store.tap([3, 2]);
    expect(fake.requests.some((r) => r.type === "combat.action")).toBe(true);
  });

  it("a waiting player's tap only inspects", () => {
    const { fake, store } = online(2);
    store.tap([3, 2]);
    expect(fake.requests.some((r) => r.type === "combat.action")).toBe(false);
  });

  it("hotseat: every side is the player's, no names", async () => {
    const { store } = await opened();
    expect(store.online.value).toBe(false);
    expect(store.myTurn.value).toBe(true);
    expect(store.sideNames.value).toBeUndefined();
  });
});
