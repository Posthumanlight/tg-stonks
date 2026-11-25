// Owns the single Phaser game: created lazily the first time a canvas screen is shown,
// hidden and put to sleep while a DOM-only screen (login, lobby) is up. Each canvas
// screen maps to one entry scene; switching screens stops the others.
import type Phaser from "phaser";

import { COMBAT_SCENE } from "../scenes/combat/CombatScene";
import { DEPLOY_SCENE } from "../scenes/combat/DeployScene";
import { startGame } from "./config";

export type CanvasView = "galaxy" | "builder" | "combat";

/** Entry scene per canvas screen. The galaxy goes through "boot", which waits for data. */
const ENTRY_SCENE: Record<CanvasView, string> = {
  galaxy: "boot",
  builder: DEPLOY_SCENE,
  combat: COMBAT_SCENE,
};

let game: Phaser.Game | null = null;
let shown: CanvasView | null = null;

export function showGame(parent: HTMLElement, view: CanvasView): void {
  // Unhide first: in RESIZE mode Phaser sizes the canvas from its parent at creation,
  // and a hidden parent measures 0×0 (the canvas would stay empty).
  parent.hidden = false;
  game ??= startGame(parent);
  game.loop.wake();
  if (shown === view) return;
  shown = view;
  for (const scene of game.scene.getScenes(true)) game.scene.stop(scene.scene.key);
  game.scene.start(ENTRY_SCENE[view]);
}

export function hideGame(parent: HTMLElement): void {
  parent.hidden = true;
  game?.loop.sleep();
}
