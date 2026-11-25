// Wiring: the app's builder store over the real API and localStorage (the logic is in
// builderStore.ts). The draft is a per-device convenience: storage may be unavailable
// (private mode, blocked site data), so every access is guarded.
import type { Draft } from "../builder/draft";
import { combatApi } from "../net/api";
import { type DraftStorage, createBuilderStore } from "./builderStore";

const DRAFT_KEY = "tg-stonks.builder-draft.v1";

const draftStorage: DraftStorage = {
  load(): unknown {
    try {
      const raw = window.localStorage.getItem(DRAFT_KEY);
      return raw ? (JSON.parse(raw) as unknown) : null;
    } catch {
      return null;
    }
  },
  save(draft: Draft | null): void {
    try {
      if (draft) window.localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
      else window.localStorage.removeItem(DRAFT_KEY);
    } catch {
      // not saved: the draft just won't survive a reload
    }
  },
};

export const builder = createBuilderStore(combatApi, draftStorage);
