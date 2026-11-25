// The custom-battle builder's state and actions (docs/client.md "Custom battle screen").
// A factory over an injected API and draft storage, so tests drive it without a server;
// state/builder.ts wires the real ones. The rules it applies are hints: the server
// validates the whole setup on Start.
import { batch, computed, signal } from "@preact/signals";

import {
  type Draft,
  type Issue,
  type UnitRef,
  dropIssue,
  draftIssues,
  fitsTemplate,
  getUnit,
  moveUnit,
  placeUnit,
  removeUnit,
  sameRef,
  setFaction,
  setModels,
  sidePoints,
  unitAtSquare,
  unitCard,
} from "../builder/draft";
import { type DragSource, type DragState, type DropTarget, IDLE, begin, hover, pick, release } from "../builder/drag";
import type { Square } from "../builder/placement";
import { ApiError } from "../net/http";
import type { BuilderView, CombatCreated, CustomCombatRequest } from "../protocol";

export interface BuilderApi {
  getBuilder(): Promise<BuilderView>;
  createCustom(body: CustomCombatRequest): Promise<CombatCreated>;
}

/** Where the draft survives a reload (per device). Failures must not throw. */
export interface DraftStorage {
  load(): unknown;
  save(draft: Draft | null): void;
}

export type TemplateState =
  | { readonly status: "idle" | "loading" }
  | { readonly status: "error"; readonly reason: string }
  | { readonly status: "ready"; readonly view: BuilderView };

/** A server rejection of the setup, located when it names a side/unit. */
export interface ServerIssue {
  readonly reason: string;
  readonly side: number | null;
  readonly unit: number | null;
}

/** The footprint under a drag, for the scene: green when `issue` is null, else red. */
export interface Ghost {
  readonly origin: Square;
  readonly size: number;
  readonly side: number;
  readonly issue: string | null;
}

const reasonOf = (error: unknown): string => (error instanceof ApiError ? error.reasonKey : "error.generic");

const clone = (draft: Draft): Draft => structuredClone(draft);

function locate(detail: unknown): { side: number | null; unit: number | null } {
  if (!detail || typeof detail !== "object") return { side: null, unit: null };
  const { side, unit } = detail as { side?: unknown; unit?: unknown };
  return {
    side: typeof side === "number" ? side : null,
    unit: typeof unit === "number" ? unit : null,
  };
}

export function createBuilderStore(api: BuilderApi, storage: DraftStorage) {
  const template = signal<TemplateState>({ status: "idle" });
  const draft = signal<Draft | null>(null);
  const activeSide = signal(0);
  const selected = signal<UnitRef | null>(null);
  const drag = signal<DragState>(IDLE);
  /** The last refused drop or edit (a `setup.*` key), shown as a hint. */
  const notice = signal<string | null>(null);
  const serverIssue = signal<ServerIssue | null>(null);
  /** Start was refused because a battle is already active (409). */
  const conflict = signal(false);
  const starting = signal(false);

  const view = computed(() => (template.value.status === "ready" ? template.value.view : null));
  const points = computed(() => {
    const v = view.value;
    const d = draft.value;
    return v && d ? d.sides.map((side) => sidePoints(v, side)) : [];
  });
  const issues = computed<Issue[]>(() => {
    const v = view.value;
    const d = draft.value;
    return v && d ? draftIssues(v, d) : [];
  });
  const canStart = computed(() => draft.value !== null && issues.value.length === 0 && !starting.value);
  const ghost = computed<Ghost | null>(() => {
    const state = drag.value;
    const v = view.value;
    const d = draft.value;
    if (state.phase === "idle" || !state.over || !v || !d) return null;
    const info = sourceInfo(v, d, state.source);
    if (!info) return null;
    return {
      origin: state.over,
      size: info.size,
      side: info.side,
      issue: dropIssue(v, d, info.side, info.size, state.over, info.moving),
    };
  });

  function sourceInfo(
    v: BuilderView,
    d: Draft,
    source: DragSource,
  ): { side: number; size: number; moving: UnitRef | null } | null {
    if (source.kind === "roster") {
      const card = unitCard(v, source.unitType);
      return card ? { side: activeSide.peek(), size: card.footprint, moving: null } : null;
    }
    const unit = getUnit(d, source.ref);
    const card = unit && unitCard(v, unit.unit_type);
    return card ? { side: source.ref.side, size: card.footprint, moving: source.ref } : null;
  }

  function commit(next: Draft): void {
    batch(() => {
      draft.value = next;
      serverIssue.value = null;
      notice.value = null;
    });
    storage.save(next);
  }

  // --- loading -------------------------------------------------------------------------

  async function load(): Promise<void> {
    const status = template.peek().status;
    if (status === "ready" || status === "loading") return;
    template.value = { status: "loading" };
    try {
      const fetched = await api.getBuilder();
      const saved = storage.load();
      batch(() => {
        draft.value = fitsTemplate(fetched, saved) ? saved : clone(fetched.defaults);
        template.value = { status: "ready", view: fetched };
      });
    } catch (error) {
      template.value = { status: "error", reason: reasonOf(error) };
    }
  }

  // --- editing -------------------------------------------------------------------------

  function setActiveSide(side: number): void {
    batch(() => {
      activeSide.value = side;
      selected.value = null;
      drag.value = IDLE;
    });
  }

  /** Callers confirm first: the side's units are removed. */
  function changeFaction(faction: string): void {
    const d = draft.peek();
    if (!d || d.sides[activeSide.peek()]?.faction === faction) return;
    selected.value = null;
    commit(setFaction(d, activeSide.peek(), faction));
  }

  function resetToDefaults(): void {
    const v = view.peek();
    if (!v) return;
    selected.value = null;
    commit(clone(v.defaults));
  }

  function select(ref: UnitRef | null): void {
    selected.value = ref;
  }

  function changeModels(models: number): void {
    const v = view.peek();
    const d = draft.peek();
    const ref = selected.peek();
    const unit = d && ref && getUnit(d, ref);
    const card = v && unit && unitCard(v, unit.unit_type);
    if (d && ref && card) commit(setModels(d, ref, card, models));
  }

  function removeSelected(): void {
    const d = draft.peek();
    const ref = selected.peek();
    if (!d || !ref) return;
    selected.value = null;
    commit(removeUnit(d, ref));
  }

  // --- gestures ------------------------------------------------------------------------

  function beginDrag(source: DragSource): void {
    batch(() => {
      if (source.kind === "token") selected.value = source.ref;
      drag.value = begin(source);
      notice.value = null;
    });
  }

  /** Tap fallback: pick a card or token up; picking the same one again puts it down. */
  function pickUp(source: DragSource): void {
    const current = drag.peek();
    const again =
      current.phase === "picked" &&
      (source.kind === "roster"
        ? current.source.kind === "roster" && current.source.unitType === source.unitType
        : current.source.kind === "token" && sameRef(current.source.ref, source.ref));
    batch(() => {
      if (source.kind === "token") selected.value = again ? null : source.ref;
      drag.value = again ? IDLE : pick(source);
      notice.value = null;
    });
  }

  function hoverSquare(square: Square | null): void {
    drag.value = hover(drag.peek(), square);
  }

  function endDrag(target: DropTarget): void {
    const { state, command } = release(drag.peek(), target);
    drag.value = state;
    const v = view.peek();
    const d = draft.peek();
    if (!command || !v || !d) return;
    switch (command.type) {
      case "place": {
        const side = activeSide.peek();
        const card = unitCard(v, command.unitType);
        if (!card) return;
        if ((d.sides[side]?.units.length ?? 0) >= v.limits.max_units_per_side) {
          notice.value = "setup.too_many_units";
          return;
        }
        const issue = dropIssue(v, d, side, card.footprint, command.at);
        if (issue) {
          notice.value = issue; // snap back
          return;
        }
        commit(placeUnit(d, side, card, command.at));
        selected.value = { side, index: d.sides[side]?.units.length ?? 0 };
        return;
      }
      case "move": {
        const unit = getUnit(d, command.ref);
        const card = unit && unitCard(v, unit.unit_type);
        if (!card) return;
        const issue = dropIssue(v, d, command.ref.side, card.footprint, command.to, command.ref);
        if (issue) {
          notice.value = issue; // snap back
          return;
        }
        commit(moveUnit(d, command.ref, command.to));
        selected.value = command.ref;
        return;
      }
      case "remove":
        selected.value = null;
        commit(removeUnit(d, command.ref));
        return;
    }
  }

  /** A tap on the board (not a drag): drop what's picked, or pick a token, or deselect. */
  function tapSquare(square: Square): void {
    const v = view.peek();
    const d = draft.peek();
    if (!v || !d) return;
    const hit = unitAtSquare(v, d, square);
    const state = drag.peek();
    const carryingToken = state.phase === "picked" && state.source.kind === "token" ? state.source.ref : null;
    if (state.phase === "picked" && (!hit || sameRef(hit, carryingToken))) {
      endDrag({ kind: "square", square });
      return;
    }
    if (hit) {
      if (hit.side !== activeSide.peek()) setActiveSide(hit.side);
      pickUp({ kind: "token", ref: hit });
      return;
    }
    batch(() => {
      selected.value = null;
      drag.value = IDLE;
    });
  }

  /** The unit under a press, if it belongs to the active side (only those can be dragged). */
  function draggableAt(square: Square): UnitRef | null {
    const v = view.peek();
    const d = draft.peek();
    const hit = v && d ? unitAtSquare(v, d, square) : null;
    return hit && hit.side === activeSide.peek() ? hit : null;
  }

  // --- start ---------------------------------------------------------------------------

  /** Send the draft. Returns the new combat's id, or null when refused (see the signals). */
  async function start(): Promise<string | null> {
    const d = draft.peek();
    if (!d || !canStart.peek()) return null;
    batch(() => {
      starting.value = true;
      serverIssue.value = null;
      conflict.value = false;
    });
    try {
      const { combat_id } = await api.createCustom(d);
      storage.save(null);
      return combat_id;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        conflict.value = true;
      } else {
        const { side, unit } = locate(error instanceof ApiError ? error.detail : null);
        batch(() => {
          serverIssue.value = { reason: reasonOf(error), side, unit };
          if (side !== null) setActiveSide(side);
          if (side !== null && unit !== null) selected.value = { side, index: unit };
        });
      }
      return null;
    } finally {
      starting.value = false;
    }
  }

  /** Forget the screen's transient state (leaving the builder keeps the draft). */
  function leave(): void {
    batch(() => {
      selected.value = null;
      drag.value = IDLE;
      notice.value = null;
      serverIssue.value = null;
      conflict.value = false;
    });
  }

  return {
    template,
    view,
    draft,
    activeSide,
    selected,
    drag,
    notice,
    serverIssue,
    conflict,
    starting,
    points,
    issues,
    canStart,
    ghost,
    load,
    setActiveSide,
    changeFaction,
    resetToDefaults,
    select,
    changeModels,
    removeSelected,
    beginDrag,
    pickUp,
    hoverSquare,
    endDrag,
    tapSquare,
    draggableAt,
    start,
    leave,
  };
}

export type BuilderStore = ReturnType<typeof createBuilderStore>;
