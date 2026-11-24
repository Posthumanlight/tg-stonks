import { t } from "../i18n";
import type { Platform } from "../platform/telegram";
import { screen } from "../state/screen";
import { GalaxyOverlay } from "./screens/GalaxyOverlay";
import { Lobby } from "./screens/Lobby";
import { Login } from "./screens/Login";

interface AppProps {
  platform: Platform;
}

/** Top-level router: one overlay per screen (docs/client.md "Screens"). */
export function App({ platform }: AppProps) {
  switch (screen.value) {
    case "boot":
      return <p class="note">{t("app.loading")}</p>;
    case "login":
      return <Login />;
    case "lobby":
      return <Lobby />;
    case "galaxy":
      return <GalaxyOverlay platform={platform} />;
    case "combat":
      return null; // phase 6
  }
}
