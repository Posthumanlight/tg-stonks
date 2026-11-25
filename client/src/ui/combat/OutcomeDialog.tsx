import { outcomeText } from "../../combat/log";
import { t } from "../../i18n";
import { combat } from "../../state/combat";
import type { OutcomeView } from "../../protocol";
import { backToLobby } from "./navigation";

/** Online: from this player's side ("Victory" / "Defeat"); hotseat: neutral. */
function title(outcome: OutcomeView): string {
  const mine = combat.mySides.value;
  if (!combat.online.value || !mine) return t("combat.outcome.title");
  if (outcome.draw) return t("combat.outcome.title");
  return outcome.winners.some((side) => mine.includes(side))
    ? t("combat.outcome.victory")
    : t("combat.outcome.defeat");
}

export function OutcomeDialog({ outcome }: { outcome: OutcomeView }) {
  return (
    <div class="note panel stack" role="dialog" aria-labelledby="outcome-title">
      <h2 id="outcome-title">{title(outcome)}</h2>
      {outcome.reason === "concede" && <p class="muted">{t("combat.outcome.conceded")}</p>}
      <p>{outcomeText(outcome.draw, outcome.winners, combat.board.value?.factions, combat.sideNames.value)}</p>
      <button type="button" class="primary" onClick={backToLobby}>
        {t("nav.back_to_lobby")}
      </button>
    </div>
  );
}
