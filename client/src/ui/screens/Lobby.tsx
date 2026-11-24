import { t } from "../../i18n";
import { currentUser, logout } from "../../state/auth";
import { goTo } from "../../state/screen";

/** Main lobby (docs/architecture.md "Lobby"): galaxy chart and the combat demo. */
export function Lobby() {
  const user = currentUser.value;
  return (
    <main class="screen-center">
      <section class="panel card stack">
        <header class="row">
          <h1>{t("lobby.title")}</h1>
          <span class="muted">{user?.username}</span>
        </header>
        <button type="button" class="primary" onClick={() => goTo("galaxy")}>
          {t("lobby.galaxy")}
        </button>
        <button type="button" disabled title={t("lobby.coming_soon")}>
          {t("lobby.combat_demo")} · {t("lobby.coming_soon")}
        </button>
        <button type="button" class="link" onClick={() => void logout()}>
          {t("auth.logout")}
        </button>
      </section>
    </main>
  );
}
