// Drag and drop for deployment as a pure state machine (docs/client.md "Custom battle
// screen"): idle → dragging | picked → idle. `release` turns the gesture into a command;
// the store checks it against the placement rule, so an invalid drop just snaps back.
import type { UnitRef } from "./draft";
import type { Square } from "./placement";

export type DragSource =
  | { readonly kind: "roster"; readonly unitType: string } // a new unit from the tray
  | { readonly kind: "token"; readonly ref: UnitRef }; // a placed unit

export type DragState =
  | { readonly phase: "idle" }
  /** Pointer held down and moving. */
  | { readonly phase: "dragging"; readonly source: DragSource; readonly over: Square | null }
  /** Tap fallback: picked up by a tap, waiting for a tap on a square. */
  | { readonly phase: "picked"; readonly source: DragSource; readonly over: Square | null };

export type DropTarget =
  | { readonly kind: "square"; readonly square: Square }
  | { readonly kind: "tray" } // back to the roster: removes a placed unit
  | { readonly kind: "none" }; // off the board: cancel

export type Command =
  | { readonly type: "place"; readonly unitType: string; readonly at: Square }
  | { readonly type: "move"; readonly ref: UnitRef; readonly to: Square }
  | { readonly type: "remove"; readonly ref: UnitRef };

export const IDLE: DragState = { phase: "idle" };

export const begin = (source: DragSource): DragState => ({ phase: "dragging", source, over: null });

export const pick = (source: DragSource): DragState => ({ phase: "picked", source, over: null });

export function hover(state: DragState, square: Square | null): DragState {
  if (state.phase === "idle") return state;
  const same = state.over && square && state.over[0] === square[0] && state.over[1] === square[1];
  return same || (state.over === null && square === null) ? state : { ...state, over: square };
}

/** End the gesture. The state is always idle afterwards. */
export function release(state: DragState, target: DropTarget): { state: DragState; command: Command | null } {
  if (state.phase === "idle") return { state, command: null };
  const { source } = state;
  let command: Command | null = null;
  if (target.kind === "square") {
    command =
      source.kind === "roster"
        ? { type: "place", unitType: source.unitType, at: target.square }
        : { type: "move", ref: source.ref, to: target.square };
  } else if (target.kind === "tray" && source.kind === "token") {
    command = { type: "remove", ref: source.ref };
  }
  return { state: IDLE, command };
}

/** The unit being carried, if any (for the ghost and for dimming the token). */
export const carried = (state: DragState): DragSource | null =>
  state.phase === "idle" ? null : state.source;
