// Shared client state as signals: the bridge between Phaser scenes and Preact overlays.
import { computed, signal } from "@preact/signals";

import { getGalaxy } from "../net/api";
import type { GalaxyView, StarView } from "../protocol";

export type GalaxyState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly galaxy: GalaxyView }
  | { readonly status: "error"; readonly message: string };

export const galaxyState = signal<GalaxyState>({ status: "loading" });

/** Index of the star the player tapped on the chart, or null. */
export const selectedStarIndex = signal<number | null>(null);

export const selectedStar = computed<StarView | null>(() => {
  const state = galaxyState.value;
  const index = selectedStarIndex.value;
  if (state.status !== "ready" || index === null) return null;
  return state.galaxy.stars[index] ?? null;
});

export async function loadGalaxy(): Promise<void> {
  galaxyState.value = { status: "loading" };
  try {
    galaxyState.value = { status: "ready", galaxy: await getGalaxy() };
  } catch (error) {
    galaxyState.value = { status: "error", message: String(error) };
  }
}

export interface StarLinkCounts {
  readonly lanes: readonly number[];
  readonly bridges: readonly number[];
}

/** Per-star number of lanes and bridges (for the star info panel). */
export const starLinkCounts = computed<StarLinkCounts | null>(() => {
  const state = galaxyState.value;
  if (state.status !== "ready") return null;
  const lanes = state.galaxy.stars.map(() => 0);
  const bridges = state.galaxy.stars.map(() => 0);
  for (const link of state.galaxy.links) {
    const counts = link.kind === "bridge" ? bridges : lanes;
    counts[link.a] = (counts[link.a] ?? 0) + 1;
    counts[link.b] = (counts[link.b] ?? 0) + 1;
  }
  return { lanes, bridges };
});
