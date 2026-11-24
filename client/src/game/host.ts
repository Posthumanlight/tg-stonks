// Owns the single Phaser game: created lazily the first time a canvas screen is shown,
// hidden and put to sleep while a DOM-only screen (login, lobby) is up.
import type Phaser from "phaser";

import { startGame } from "./config";

let game: Phaser.Game | null = null;

export function showGame(parent: HTMLElement): void {
  game ??= startGame(parent);
  parent.hidden = false;
  game.loop.wake();
}

export function hideGame(parent: HTMLElement): void {
  parent.hidden = true;
  game?.loop.sleep();
}
