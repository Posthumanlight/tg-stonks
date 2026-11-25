import { useState } from "preact/hooks";

import { t, tError } from "../../i18n";
import { ApiError } from "../../net/http";
import { currentUser, logout } from "../../state/auth";
import { combat } from "../../state/combat";
import { goTo } from "../../state/screen";

/** Main lobby (docs/architecture.md "Lobby"): galaxy chart and the combat demo. */
export function Lobby() {
  const user = currentUser.value;
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const openDemo = async () => {
    setOpening(true);
    setError(null);
    try {
      await combat.openDemo();
      goTo("combat");
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.reasonKey : "error.generic");
    } finally {
      setOpening(false);
    }
  };

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
        <button type="button" disabled={opening} onClick={() => void openDemo()}>
          {opening ? t("lobby.opening") : t("lobby.combat_demo")}
        </button>
        {error && (
          <p class="error" role="alert">
            {tError(error)}
          </p>
        )}
        <button type="button" class="link" onClick={() => void logout()}>
          {t("auth.logout")}
        </button>
      </section>
    </main>
  );
}
