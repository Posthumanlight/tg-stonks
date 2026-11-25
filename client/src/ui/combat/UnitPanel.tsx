import { sideLabel, unitLabel } from "../../combat/log";
import { t, tKey } from "../../i18n";
import { sideCss } from "../../scenes/combat/palette";
import { combat } from "../../state/combat";

/** The inspected (else active) unit: side, models per group, statuses. */
export function UnitPanel() {
  const unit = combat.shownUnit.value;
  const units = combat.view.value?.units ?? [];
  if (!unit) return <p class="muted">{t("combat.inspect_hint")}</p>;

  return (
    <div class="unit-panel">
      <div class="row">
        <strong>
          <span class="side-dot" style={{ background: sideCss(unit.side) }} />
          {unitLabel(units, unit.uid)}
        </strong>
        <span class="muted">
          {sideLabel(unit.side, combat.board.value?.factions)} · {t("combat.models", { models: unit.models })}
          {unit.wounded && ` · ${t("combat.wounded")}`}
        </span>
      </div>
      <div class="muted">
        {unit.groups
          .map((g) => `${tKey(`role.${g.role}.name`)} ${g.alive}/${g.initial} (${g.hp} HP)`)
          .join(" · ")}
        {unit.statuses.map((s) => ` · ${tKey(`ability.${s.status}.name`)} (${s.rounds_left})`).join("")}
      </div>
    </div>
  );
}
