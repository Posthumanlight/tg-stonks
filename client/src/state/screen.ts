// Which top-level screen is shown (docs/client.md "Screens").
import { signal } from "@preact/signals";

export type Screen = "boot" | "login" | "lobby" | "galaxy" | "combat";

export const screen = signal<Screen>("boot");

/** Pure: where to go when the signed-in state is (re)decided. */
export function screenAfterAuth(current: Screen, signedIn: boolean): Screen {
  if (!signedIn) return "login";
  return current === "boot" || current === "login" ? "lobby" : current;
}

export function goTo(next: Screen): void {
  screen.value = next;
}
