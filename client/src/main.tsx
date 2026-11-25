import "./ui/styles.css";

import { effect } from "@preact/signals";
import { render } from "preact";

import { hideGame, showGame } from "./game/host";
import { initI18n, t } from "./i18n";
import { bootstrapAuth, currentUser } from "./state/auth";
import { builder } from "./state/builder";
import { combat } from "./state/combat";
import { ensureGalaxy } from "./state/galaxy";
import { screen, screenAfterAuth } from "./state/screen";
import { App } from "./ui/App";

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
  } else if (current === "builder") {
    showGame(gameRoot, "builder");
    void builder.load();
  } else if (current === "combat") {
    showGame(gameRoot, "combat");
  } else {
    hideGame(gameRoot);
  }
  // However the combat screen was left (back button, sign-out), drop the fight's socket.
  if (current !== "combat" && combat.combatId.peek() !== null) combat.leave();
  if (current !== "builder") builder.leave(); // the draft itself is kept
});

// Signing in or out (including a session that expires) moves between screens.
void bootstrapAuth().finally(() => {
  screen.value = screenAfterAuth("boot", currentUser.peek() !== null);
  effect(() => {
    const signedIn = currentUser.value !== null;
    screen.value = screenAfterAuth(screen.peek(), signedIn);
  });
});
