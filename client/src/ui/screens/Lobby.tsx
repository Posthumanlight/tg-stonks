import { useEffect, useState } from "preact/hooks";

import { t, tError } from "../../i18n";
import { ApiError, combatApi } from "../../net/api";
import type { CombatSummaryView } from "../../protocol";
import { currentUser, logout } from "../../state/auth";
import { combat } from "../../state/combat";
import { goTo } from "../../state/screen";
import { findActiveCombat, openCombat } from "../combat/navigation";

const reasonOf = (failure: unknown): string =>
  failure instanceof ApiError ? failure.reasonKey : "error.generic";

/** Main lobby (docs/architecture.md "Lobby"): galaxy chart, custom and quick battles,
 * and Resume/Abandon while a battle is active. */
export function Lobby() {
  const user = currentUser.value;
  const [active, setActive] = useState<CombatSummaryView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    findActiveCombat()
      .then((found) => live && setActive(found))
      .catch(() => {}); // the buttons still work; the server enforces one battle
    return () => {
      live = false;
    };
  }, []);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(reasonOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const quickBattle = () =>
    run(async () => {
      await combat.openDemo();
      goTo("combat");
    });

  const abandon = (id: string) =>
    run(async () => {
      if (!window.confirm(t("lobby.abandon_confirm"))) return;
      await combatApi.abandon(id);
      setActive(null);
    });

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
        {active ? (
          <div class="stack-tight">
            <p class="muted">{t("lobby.active")}</p>
            <div class="row">
              <button type="button" class="primary" disabled={busy} onClick={() => openCombat(active.combat_id)}>
                {t("lobby.resume")}
              </button>
              <button type="button" disabled={busy} onClick={() => void abandon(active.combat_id)}>
                {t("lobby.abandon")}
              </button>
            </div>
          </div>
        ) : (
          <>
            <button type="button" disabled={busy} onClick={() => goTo("builder")}>
              {t("lobby.custom_battle")}
            </button>
            <button type="button" disabled={busy} onClick={() => void quickBattle()}>
              {busy ? t("lobby.opening") : t("lobby.quick_battle")}
            </button>
          </>
        )}
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
