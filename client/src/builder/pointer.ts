// The bridge from DOM pointer positions to board squares. The deploy scene installs its
// mapper while it runs, so DOM code (dragging a roster card onto the canvas) needs no
// Phaser import and works without the scene (returns null).
import type { Square } from "./placement";

export type SquareAtClient = (clientX: number, clientY: number) => Square | null;

let mapper: SquareAtClient | null = null;

export const boardPointer = {
  install(next: SquareAtClient | null): void {
    mapper = next;
  },
  squareAt(clientX: number, clientY: number): Square | null {
    return mapper?.(clientX, clientY) ?? null;
  },
};

/** The roster tray marks itself with this attribute: dropping a token there removes it. */
export const TRAY_ATTR = "data-drop-tray";

export function overTray(clientX: number, clientY: number): boolean {
  return document.elementFromPoint(clientX, clientY)?.closest(`[${TRAY_ATTR}]`) != null;
}
