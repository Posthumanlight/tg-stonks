// Wiring: the app's builder store over the real API and localStorage (the logic is in
// builderStore.ts). The draft is a per-device convenience: storage may be unavailable
// (private mode, blocked site data), so every access is guarded.
import type { Draft } from "../builder/draft";
import { combatApi } from "../net/api";
import { type DraftStorage, createBuilderStore } from "./builderStore";

// One entry per mode (and room side); the hotseat key predates rooms.
const draftKey = (key: string): string =>
  key === "hotseat" ? "tg-stonks.builder-draft.v1" : `tg-stonks.builder-draft.${key}.v1`;

const draftStorage: DraftStorage = {
  load(key: string): unknown {
    try {
      const raw = window.localStorage.getItem(draftKey(key));
      return raw ? (JSON.parse(raw) as unknown) : null;
    } catch {
      return null;
    }
  },
  save(key: string, draft: Draft | null): void {
    try {
      if (draft) window.localStorage.setItem(draftKey(key), JSON.stringify(draft));
      else window.localStorage.removeItem(draftKey(key));
    } catch {
      // not saved: the draft just won't survive a reload
    }
  },
};

export const builder = createBuilderStore(combatApi, draftStorage);
