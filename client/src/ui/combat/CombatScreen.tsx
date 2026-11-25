import { t, tError } from "../../i18n";
import { unitLabel } from "../../combat/log";
import { combat } from "../../state/combat";
import { ActionBar } from "./ActionBar";
import { CombatLog } from "./CombatLog";
import { ConnectionNotice } from "./ConnectionNotice";
import { backToLobby } from "./navigation";
import { OutcomeDialog } from "./OutcomeDialog";
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
