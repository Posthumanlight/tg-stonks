import { t } from "../i18n";
import { screen } from "../state/screen";
import { BuilderScreen } from "./builder/BuilderScreen";
import { CombatScreen } from "./combat/CombatScreen";
import { GalaxyOverlay } from "./screens/GalaxyOverlay";
import { Lobby } from "./screens/Lobby";
import { Login } from "./screens/Login";
import { RoomScreen } from "./rooms/RoomScreen";
import { RoomsScreen } from "./rooms/RoomsScreen";

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
    case "rooms":
      return <RoomsScreen />;
    case "room":
      return <RoomScreen />;
    case "combat":
      return <CombatScreen />;
  }
}
