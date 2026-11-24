// Thin adapter over the Telegram Mini App API (telegram-web-app.js, loaded in index.html).
// Everything degrades to a no-op in a normal browser, so the rest of the client never
// checks the host directly.
import type { WebApp } from "telegram-web-app";

export type PlatformKind = "telegram" | "web";

export interface Platform {
  readonly kind: PlatformKind;
  /** BCP 47-ish code from Telegram's user, or the browser. */
  readonly languageCode: string | undefined;
  /** Raw signed initData for server-side HMAC verification ("" on web). Unused until auth. */
  readonly initData: string;
  /** Show Telegram's native back button with `handler`, or hide it with `null`. */
  setBackButton(handler: (() => void) | null): void;
}

const BACKGROUND = "#05070d";

function telegramApp(): WebApp | undefined {
  const app = window.Telegram?.WebApp;
  // The script defines WebApp everywhere; only inside Telegram is initData non-empty.
  return app && app.initData ? app : undefined;
}

export function initPlatform(): Platform {
  const app = telegramApp();
  if (!app) {
    return {
      kind: "web",
      languageCode: navigator.language,
      initData: "",
      setBackButton: () => {},
    };
  }

  app.ready();
  app.expand();
  if (app.isVersionAtLeast("6.1")) {
    app.setHeaderColor(BACKGROUND);
    app.setBackgroundColor(BACKGROUND);
  }
  // Without this, dragging the star chart downwards would minimize/close the Mini App.
  if (app.isVersionAtLeast("7.7")) app.disableVerticalSwipes();

  let current: (() => void) | null = null;
  return {
    kind: "telegram",
    languageCode: app.initDataUnsafe.user?.language_code,
    initData: app.initData,
    setBackButton(handler) {
      if (!app.isVersionAtLeast("6.1")) return;
      if (current) app.BackButton.offClick(current);
      current = handler;
      if (handler) {
        app.BackButton.onClick(handler);
        app.BackButton.show();
      } else {
        app.BackButton.hide();
      }
    },
  };
}
