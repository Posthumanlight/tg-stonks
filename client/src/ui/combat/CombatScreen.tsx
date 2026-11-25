import { useState } from "preact/hooks";

import { t, tError } from "../../i18n";
import { unitLabel } from "../../combat/log";
import { ApiError, combatApi } from "../../net/api";
import { combat } from "../../state/combat";
import { ActionBar } from "./ActionBar";
import { CombatLog } from "./CombatLog";
import { ConnectionNotice } from "./ConnectionNotice";
import { backToLobby } from "./navigation";
import { OutcomeDialog } from "./OutcomeDialog";
import { TurnTimer } from "./TurnTimer";
import { UnitPanel } from "./UnitPanel";

/** DOM overlay above the combat board (docs/client.md "Combat screen"). */
export function CombatScreen() {
  const view = combat.view.value;
  const active = combat.activeUnit.value;
  const error = combat.lastError.value;

  return (
    <>
      <header class="topbar panel">
        <button type="button" class="icon" onClick={backToLobby} aria-label={t("nav.back_to_lobby")}>
          ‹
        </button>
        <h1>{view ? t("combat.round", { round: view.round }) : t("combat.title")}</h1>
        <span class="muted">{active ? unitLabel(view?.units ?? [], active.uid) : ""}</span>
        <TurnTimer />
        {combat.online.value && view && !view.outcome && <SurrenderButton />}
      </header>

      <ConnectionNotice />

      {!view && <p class="note">{t("combat.loading")}</p>}

      {view && (
        <section class="combat-dock panel">
          <UnitPanel />
          <ActionBar />
          {error && (
            <p class="error" role="alert">
              {tError(error)}
            </p>
          )}
          <CombatLog />
        </section>
      )}

      {view?.outcome && <OutcomeDialog outcome={view.outcome} />}
    </>
  );
}

/** Online battles: leaving is a surrender (the server ends it; the outcome is pushed). */
function SurrenderButton() {
  const [error, setError] = useState<string | null>(null);
  const surrender = async () => {
    const id = combat.combatId.peek();
    if (!id || !window.confirm(t("combat.surrender_confirm"))) return;
    try {
      await combatApi.abandon(id);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.reasonKey : "error.generic");
    }
  };
  return (
    <>
      <button type="button" onClick={() => void surrender()}>
        {t("combat.surrender")}
      </button>
      {error && <span class="error">{tError(error)}</span>}
    </>
  );
}
