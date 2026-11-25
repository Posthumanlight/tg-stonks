import { getUnit, unitCard } from "../../builder/draft";
import { t, tKey } from "../../i18n";
import { builder } from "../../state/builder";

/** The selected token: its model count (within the unit's range), points, Remove. */
export function DeployPanel() {
  const view = builder.view.value;
  const draft = builder.draft.value;
  const ref = builder.selected.value;
  const unit = draft && ref ? getUnit(draft, ref) : undefined;
  const card = view && unit ? unitCard(view, unit.unit_type) : undefined;
  if (!ref || !unit || !card) return null;

  const { min, max } = card.models;
  return (
    <div class="deploy-panel row">
      <strong>{tKey(card.name_key)}</strong>
      <span class="muted">{t("builder.points", { points: card.points })}</span>
      {min < max && (
        <span class="stepper" role="group" aria-label={t("builder.models")}>
          <button type="button" class="icon" disabled={unit.models <= min} onClick={() => builder.changeModels(unit.models - 1)}>
            −
          </button>
          <output>{unit.models}</output>
          <button type="button" class="icon" disabled={unit.models >= max} onClick={() => builder.changeModels(unit.models + 1)}>
            +
          </button>
        </span>
      )}
      <button type="button" onClick={() => builder.removeSelected()}>
        {t("builder.remove")}
      </button>
    </div>
  );
}
