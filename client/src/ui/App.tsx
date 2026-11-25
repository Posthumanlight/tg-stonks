import { t } from "../i18n";
import { screen } from "../state/screen";
import { BuilderScreen } from "./builder/BuilderScreen";
import { CombatScreen } from "./combat/CombatScreen";
import { GalaxyOverlay } from "./screens/GalaxyOverlay";
import { Lobby } from "./screens/Lobby";
import { Login } from "./screens/Login";

/** Top-level router: one overlay per screen (docs/client.md "Screens"). */
export function App() {
  switch (screen.value) {
    case "boot":
      return <p class="note">{t("app.loading")}</p>;
    case "login":
      return <Login />;
    case "lobby":
      return <Lobby />;
    case "galaxy":
      return <GalaxyOverlay />;
    case "builder":
      return <BuilderScreen />;
    case "combat":
      return <CombatScreen />;
  }
}
