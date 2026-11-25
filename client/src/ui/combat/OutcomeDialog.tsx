import { outcomeText } from "../../combat/log";
import { t } from "../../i18n";
import type { OutcomeView } from "../../protocol";
import { backToLobby } from "./navigation";

export function OutcomeDialog({ outcome }: { outcome: OutcomeView }) {
  return (
    <div class="note panel stack" role="dialog" aria-labelledby="outcome-title">
      <h2 id="outcome-title">{t("combat.outcome.title")}</h2>
      <p>{outcomeText(outcome.draw, outcome.winners)}</p>
      <button type="button" class="primary" onClick={backToLobby}>
        {t("nav.back_to_lobby")}
      </button>
    </div>
  );
}
