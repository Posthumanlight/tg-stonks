import "./ui/styles.css";

import { effect } from "@preact/signals";
import { render } from "preact";

import { hideGame, showGame } from "./game/host";
import { initI18n, t } from "./i18n";
import { bootstrapAuth, currentUser } from "./state/auth";
import { builder } from "./state/builder";
import { combat } from "./state/combat";
import { ensureGalaxy } from "./state/galaxy";
import { room } from "./state/rooms";
import { goTo, screen, screenAfterAuth } from "./state/screen";
import { App } from "./ui/App";
import { openCombat } from "./ui/combat/navigation";

function mustGet(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`#${id} missing from index.html`);
  return element;
}

initI18n();
document.title = t("app.title");

const gameRoot = mustGet("game");
render(<App />, mustGet("ui"));

// Canvas screens show the Phaser game; DOM-only screens hide it.
effect(() => {
  const current = screen.value;
  if (current === "galaxy") {
    showGame(gameRoot, "galaxy");
    ensureGalaxy();
  } else if (current === "builder" || current === "room") {
    showGame(gameRoot, "builder"); // a room deploys on the same scene
    void builder.load();
  } else if (current === "combat") {
    showGame(gameRoot, "combat");
  } else {
    hideGame(gameRoot);
  }
  // However the combat screen was left (back button, sign-out), drop the fight's socket.
  if (current !== "combat" && combat.combatId.peek() !== null) combat.leave();
  // Leaving a room's screen stops watching it (the battle keeps the socket open).
  if (current !== "room" && room.roomId.peek() !== null) room.detach(current !== "combat");
  if (current !== "room") builder.exitRoom();
  if (current !== "builder" && current !== "room") builder.leave(); // drafts are kept
});

// A room on screen: the builder edits the player's side, locked while they're ready.
effect(() => {
  const view = room.room.value;
  if (screen.value !== "room" || !view) return;
  const mode = builder.mode.peek();
  if (mode.kind !== "room" || mode.side !== view.your_side || mode.pointsLimit !== view.points_limit) {
    void builder.enterRoom({ side: view.your_side, pointsLimit: view.points_limit, army: view.your_army });
  } else {
    builder.setLocked(room.me.value?.ready ?? false);
  }
});

// Both ready: the room hands over to its battle. Closed: back to the lobby (it says why).
effect(() => {
  const combatId = room.started.value;
  if (combatId) openCombat(combatId);
});
effect(() => {
  if (room.closed.value && screen.peek() === "room") goTo("lobby");
});

// Signing in or out (including a session that expires) moves between screens.
void bootstrapAuth().finally(() => {
  screen.value = screenAfterAuth("boot", currentUser.peek() !== null);
  effect(() => {
    const signedIn = currentUser.value !== null;
    screen.value = screenAfterAuth(screen.peek(), signedIn);
  });
});
