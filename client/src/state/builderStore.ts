// The custom-battle builder's state and actions (docs/client.md "Custom battle screen").
// A factory over an injected API and draft storage, so tests drive it without a server;
// state/builder.ts wires the real ones. The rules it applies are hints: the server
// validates the whole setup on Start (or on Ready, in a room).
//
// Two modes share everything (scene, roster, drag and drop): `hotseat` edits both sides
// on the whole board; `room` edits only the player's side, inside its deployment zone
// and the room's points limit, and the opponent's side stays empty (hidden).
import { batch, computed, signal } from "@preact/signals";

import {
  type Draft,
  type Issue,
  type IssueScope,
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
import type { BuilderView, CombatCreated, CustomCombatRequest, SideSetup } from "../protocol";

export interface BuilderApi {
  getBuilder(): Promise<BuilderView>;
  createCustom(body: CustomCombatRequest): Promise<CombatCreated>;
}

/** Where drafts survive a reload (per device), one per `key` (the mode, and a room
 * side). Failures must not throw. */
export interface DraftStorage {
  load(key: string): unknown;
  save(key: string, draft: Draft | null): void;
}

export type BuilderMode =
  | { readonly kind: "hotseat" }
  | { readonly kind: "room"; readonly side: number; readonly pointsLimit: number };

/** Entering a room: the player's side, the room's limit, and their locked army if they
 * had already readied (a reconnect). */
export interface RoomEntry {
  readonly side: number;
  readonly pointsLimit: number;
  readonly army: SideSetup | null;
}

const HOTSEAT: BuilderMode = { kind: "hotseat" };

const storageKey = (mode: BuilderMode): string => (mode.kind === "room" ? `room${mode.side}` : "hotseat");

/** A room draft: the player's side, and the opponent's side kept empty. */
function roomDraft(template: BuilderView, side: number, mine: SideSetup): Draft {
  const [a, b] = template.defaults.sides;
  const hidden = (s: SideSetup): SideSetup => ({ faction: s.faction, units: [] });
  return { sides: side === 0 ? [mine, hidden(b)] : [hidden(a), mine] };
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
  const mode = signal<BuilderMode>(HOTSEAT);
  /** The army is submitted (Ready in a room): no edits until unlocked. */
  const locked = signal(false);
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

  const loaded = computed(() => (template.value.status === "ready" ? template.value.view : null));
  /** The template as this mode sees it: rooms deploy inside the room zones. */
  const view = computed<BuilderView | null>(() => {
    const v = loaded.value;
    if (!v || mode.value.kind === "hotseat") return v;
    return { ...v, zones: v.rooms.zones };
  });
  const scope = computed<IssueScope>(() => {
    const m = mode.value;
    return m.kind === "room" ? { sides: [m.side], pointsLimit: m.pointsLimit } : {};
  });
  const points = computed(() => {
    const v = view.value;
    const d = draft.value;
    return v && d ? d.sides.map((side) => sidePoints(v, side)) : [];
  });
  const issues = computed<Issue[]>(() => {
    const v = view.value;
    const d = draft.value;
    return v && d ? draftIssues(v, d, scope.value) : [];
  });
  const canStart = computed(
    () => draft.value !== null && issues.value.length === 0 && !starting.value && !locked.value,
  );
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
    if (locked.peek()) return;
    batch(() => {
      draft.value = next;
      serverIssue.value = null;
      notice.value = null;
    });
    storage.save(storageKey(mode.peek()), next);
  }

  // --- loading -------------------------------------------------------------------------

  async function load(): Promise<void> {
    const status = template.peek().status;
    if (status === "ready" || status === "loading") return;
    template.value = { status: "loading" };
    try {
      const fetched = await api.getBuilder();
      const saved = storage.load(storageKey(HOTSEAT));
      batch(() => {
        draft.value = fitsTemplate(fetched, saved) ? saved : clone(fetched.defaults);
        template.value = { status: "ready", view: fetched };
      });
    } catch (error) {
      template.value = { status: "error", reason: reasonOf(error) };
    }
  }

  // --- modes ---------------------------------------------------------------------------

  /** Switch to a room's side. The player's draft for that side comes from their locked
   * army, else this device's saved room draft, else the defaults. */
  async function enterRoom(entry: RoomEntry): Promise<void> {
    await load();
    const v = loaded.peek();
    if (!v) return;
    const next: BuilderMode = { kind: "room", side: entry.side, pointsLimit: entry.pointsLimit };
    const saved = storage.load(storageKey(next));
    const savedSide = fitsTemplate(v, saved) ? saved.sides[entry.side] : undefined;
    const mine =
      entry.army ??
      (savedSide && savedSide.units.length > 0 ? savedSide : v.defaults.sides[entry.side]) ??
      { faction: v.factions[0]?.id ?? "", units: [] };
    batch(() => {
      mode.value = next;
      activeSide.value = entry.side;
      locked.value = entry.army !== null;
      draft.value = roomDraft(v, entry.side, structuredClone(mine));
      leave();
    });
  }

  /** Back to the hotseat builder and its own draft. */
  function exitRoom(): void {
    if (mode.peek().kind === "hotseat") return;
    const v = loaded.peek();
    const saved = storage.load(storageKey(HOTSEAT));
    batch(() => {
      mode.value = HOTSEAT;
      activeSide.value = 0;
      locked.value = false;
      draft.value = v ? (fitsTemplate(v, saved) ? saved : clone(v.defaults)) : null;
      leave();
    });
  }

  function setLocked(value: boolean): void {
    batch(() => {
      locked.value = value;
      if (value) {
        selected.value = null;
        drag.value = IDLE;
      }
    });
  }

  /** The player's side in a room (null in hotseat). */
  function roomSide(): number | null {
    const m = mode.peek();
    return m.kind === "room" ? m.side : null;
  }

  // --- editing -------------------------------------------------------------------------

  function setActiveSide(side: number): void {
    const own = roomSide();
    if (own !== null && side !== own) return; // a room shows only the player's side
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
    const own = roomSide();
    const defaults = clone(v.defaults);
    const mine = own !== null ? defaults.sides[own] : undefined;
    commit(own !== null && mine ? roomDraft(v, own, mine) : defaults);
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
    if (locked.peek()) return;
    batch(() => {
      if (source.kind === "token") selected.value = source.ref;
      drag.value = begin(source);
      notice.value = null;
    });
  }

  /** Tap fallback: pick a card or token up; picking the same one again puts it down. */
  function pickUp(source: DragSource): void {
    if (locked.peek()) return;
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
    if (!v || !d || locked.peek()) return;
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
    return hit && hit.side === activeSide.peek() && !locked.peek() ? hit : null;
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
      storage.save(storageKey(HOTSEAT), null);
      return combat_id;
    } catch (error) {
      reject(error);
      return null;
    } finally {
      starting.value = false;
    }
  }

  /** Show the server's refusal of the setup: a 409 conflict, or a located issue. */
  function reject(error: unknown): void {
    if (error instanceof ApiError && error.status === 409 && error.reasonKey === "combat.already_active") {
      conflict.value = true;
      return;
    }
    const { side, unit } = locate(error instanceof ApiError ? error.detail : null);
    batch(() => {
      serverIssue.value = { reason: reasonOf(error), side, unit };
      if (side !== null) setActiveSide(side);
      if (side !== null && unit !== null) selected.value = { side, index: unit };
    });
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
    mode,
    locked,
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
    reject,
    leave,
    enterRoom,
    exitRoom,
    setLocked,
  };
}

export type BuilderStore = ReturnType<typeof createBuilderStore>;
