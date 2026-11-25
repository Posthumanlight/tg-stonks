import { describe, expect, it, vi } from "vitest";

import type { Draft } from "../builder/draft";
import { WALKER, builderView } from "../builder/fixtures";
import { ApiError } from "../net/http";
import type { BuilderView } from "../protocol";
import { type BuilderApi, type DraftStorage, createBuilderStore } from "./builderStore";

function setup(options: { saved?: unknown; view?: BuilderView; api?: Partial<BuilderApi> } = {}) {
  const view = options.view ?? builderView();
  const drafts = new Map<string, unknown>([["hotseat", options.saved ?? null]]);
  const storage: DraftStorage = {
    load: (key: string) => drafts.get(key) ?? null,
    save: (key: string, draft: Draft | null) => {
      drafts.set(key, draft);
    },
  };
  const saved = (key = "hotseat") => drafts.get(key) ?? null;
  const api: BuilderApi = {
    getBuilder: vi.fn(async () => view),
    createCustom: vi.fn(async () => ({ combat_id: "c1" })),
    ...options.api,
  };
  const store = createBuilderStore(api, storage);
  return { store, api, view, saved };
}

describe("loading", () => {
  it("starts from the defaults, or a saved draft that still fits", async () => {
    const fresh = setup();
    await fresh.store.load();
    expect(fresh.store.draft.value).toEqual(fresh.view.defaults);
    expect(fresh.store.draft.value).not.toBe(fresh.view.defaults); // a copy

    const savedDraft = { sides: [{ faction: "brood", units: [] }, fresh.view.defaults.sides[1]] };
    const restored = setup({ saved: savedDraft });
    await restored.store.load();
    expect(restored.store.draft.value).toEqual(savedDraft);

    const stale = setup({ saved: { sides: [{ faction: "gone", units: [] }] } });
    await stale.store.load();
    expect(stale.store.draft.value).toEqual(stale.view.defaults);
  });

  it("reports a failed load, and loads once", async () => {
    const { store, api } = setup({
      api: { getBuilder: vi.fn(async () => Promise.reject(new ApiError(503, "combat.unavailable"))) },
    });
    await store.load();
    expect(store.template.value).toEqual({ status: "error", reason: "combat.unavailable" });
    expect(api.getBuilder).toHaveBeenCalledTimes(1);
  });
});

describe("drag and drop", () => {
  it("places a dragged card, shows the ghost, and saves the draft", async () => {
    const { store, saved } = setup();
    await store.load();
    store.beginDrag({ kind: "roster", unitType: WALKER.unit_type });
    store.hoverSquare([4, 2]);
    expect(store.ghost.value).toEqual({ origin: [4, 2], size: 2, side: 0, issue: null });
    store.endDrag({ kind: "square", square: [4, 2] });
    expect(store.draft.value?.sides[0].units[1]).toEqual({ unit_type: "bastion_walker", models: 1, origin: [4, 2] });
    expect(store.selected.value).toEqual({ side: 0, index: 1 });
    expect(saved()).toEqual(store.draft.value);
    expect(store.points.value).toEqual([250, 80]);
  });

  it("snaps an invalid drop back with the reason", async () => {
    const { store } = setup();
    await store.load();
    store.beginDrag({ kind: "token", ref: { side: 0, index: 0 } });
    store.hoverSquare([3, 1]);
    expect(store.ghost.value?.issue).toBe("setup.blocked_square");
    store.endDrag({ kind: "square", square: [3, 1] });
    expect(store.draft.value?.sides[0].units[0]?.origin).toEqual([0, 0]);
    expect(store.notice.value).toBe("setup.blocked_square");
    expect(store.drag.value.phase).toBe("idle");
  });

  it("removes a token dropped on the tray", async () => {
    const { store } = setup();
    await store.load();
    store.beginDrag({ kind: "token", ref: { side: 0, index: 0 } });
    store.endDrag({ kind: "tray" });
    expect(store.draft.value?.sides[0].units).toEqual([]);
    expect(store.canStart.value).toBe(false); // an empty side
  });

  it("refuses units past the per-side cap", async () => {
    const { store } = setup();
    await store.load();
    for (const x of [2, 4, 6]) {
      store.beginDrag({ kind: "roster", unitType: "line_troopers" });
      store.endDrag({ kind: "square", square: [x, 5] });
    }
    expect(store.draft.value?.sides[0].units).toHaveLength(3);
    expect(store.notice.value).toBe("setup.too_many_units");
  });

  it("tap fallback: tap a token, then a square; other side's tokens switch tabs", async () => {
    const { store } = setup();
    await store.load();
    store.tapSquare([0, 0]);
    expect(store.selected.value).toEqual({ side: 0, index: 0 });
    store.tapSquare([2, 2]);
    expect(store.draft.value?.sides[0].units[0]?.origin).toEqual([2, 2]);

    store.tapSquare([7, 5]);
    expect(store.activeSide.value).toBe(1);
    expect(store.selected.value).toEqual({ side: 1, index: 0 });
    expect(store.draggableAt([2, 2])).toBeNull(); // side 0 isn't active now

    store.pickUp({ kind: "roster", unitType: "ravager_swarm" });
    store.tapSquare([6, 0]);
    expect(store.draft.value?.sides[1].units).toHaveLength(2);
  });
});

describe("start", () => {
  it("sends the draft and clears the saved copy", async () => {
    const { store, api, saved } = setup();
    await store.load();
    expect(store.canStart.value).toBe(true);
    expect(await store.start()).toBe("c1");
    expect(api.createCustom).toHaveBeenCalledWith(store.draft.value);
    expect(saved()).toBeNull();
  });

  it("locates a server rejection on the offending unit", async () => {
    const { store } = setup({
      api: {
        createCustom: vi.fn(async () =>
          Promise.reject(new ApiError(400, "setup.overlap", undefined, { side: 1, unit: 0 })),
        ),
      },
    });
    await store.load();
    expect(await store.start()).toBeNull();
    expect(store.serverIssue.value).toEqual({ reason: "setup.overlap", side: 1, unit: 0 });
    expect(store.activeSide.value).toBe(1);
    expect(store.selected.value).toEqual({ side: 1, index: 0 });
  });

  it("flags an already active battle", async () => {
    const { store } = setup({
      api: { createCustom: vi.fn(async () => Promise.reject(new ApiError(409, "combat.already_active"))) },
    });
    await store.load();
    expect(await store.start()).toBeNull();
    expect(store.conflict.value).toBe(true);
    expect(store.serverIssue.value).toBeNull();
  });
});

describe("room mode", () => {
  it("edits only the player's side, inside its zone and the points limit", async () => {
    const { store, saved } = setup();
    await store.enterRoom({ side: 1, pointsLimit: 200, army: null });
    expect(store.activeSide.value).toBe(1);
    expect(store.view.value?.zones).toEqual(store.view.value?.rooms.zones); // the room zones
    expect(store.draft.value?.sides[0]?.units).toEqual([]); // the opponent's side stays hidden
    expect(store.draft.value?.sides[1]?.units).toHaveLength(1); // the defaults for side 1
    expect(store.issues.value).toEqual([]); // side 0 (empty) isn't checked
    store.setActiveSide(0);
    expect(store.activeSide.value).toBe(1);

    store.beginDrag({ kind: "roster", unitType: "ravager_swarm" });
    store.endDrag({ kind: "square", square: [2, 2] }); // outside side 1's rows (4-5)
    expect(store.notice.value).toBe("setup.outside_zone");
    store.beginDrag({ kind: "roster", unitType: "ravager_swarm" });
    store.endDrag({ kind: "square", square: [2, 4] });
    store.beginDrag({ kind: "roster", unitType: "ravager_swarm" });
    store.endDrag({ kind: "square", square: [4, 4] });
    expect(store.issues.value).toEqual([{ side: 1, unit: null, reason: "setup.over_points" }]); // 240 > 200
    expect(store.canStart.value).toBe(false);
    expect(saved("room1")).toEqual(store.draft.value); // its own saved draft
    expect(saved("hotseat")).toBeNull();
  });

  it("a locked (ready) army can't change; exiting restores the hotseat draft", async () => {
    const { store } = setup();
    await store.load();
    const hotseat = store.draft.value;
    const army = { faction: "brood", units: [{ unit_type: "ravager_swarm", models: 12, origin: [1, 5] as [number, number] }] };
    await store.enterRoom({ side: 1, pointsLimit: 0, army });
    expect(store.locked.value).toBe(true);
    expect(store.draft.value?.sides[1]).toEqual(army);
    store.tapSquare([1, 5]);
    expect(store.selected.value).toBeNull();
    store.beginDrag({ kind: "token", ref: { side: 1, index: 0 } });
    expect(store.drag.value.phase).toBe("idle");
    expect(store.canStart.value).toBe(false);
    store.setLocked(false);
    expect(store.canStart.value).toBe(true);

    store.exitRoom();
    expect(store.mode.value.kind).toBe("hotseat");
    expect(store.draft.value).toEqual(hotseat);
  });
});
