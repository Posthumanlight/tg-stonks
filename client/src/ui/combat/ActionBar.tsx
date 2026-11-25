import { weaponChoices } from "../../combat/interaction";
import { t, tKey } from "../../i18n";
import { combat } from "../../state/combat";

/** The active unit's options, straight from the server's `legal` (no client rules). */
export function ActionBar() {
  const legal = combat.legal.value;
  const active = combat.view.value?.active;
  const mode = combat.mode.value;
  if (!legal || !active) return null;
  if (!combat.myTurn.value) {
    return <p class="muted">{t("combat.opponent_turn")}</p>; // look, don't touch
  }

  const disabled = combat.busy.value || combat.connection.value !== "open";
  const hint =
    mode.kind === "attack"
      ? t("combat.hint.attack")
      : mode.kind === "ability"
        ? t("combat.hint.ability")
        : t("combat.hint.move");

  return (
    <div class="stack-tight">
      <div class="row muted">
        <span>
          {t("combat.ap", { ap: active.ap_left })} · {t("combat.movement", { movement: active.movement_left })}
        </span>
        <span>{hint}</span>
      </div>
      <div class="actions">
        {weaponChoices(legal).map((choice) => (
          <button
            type="button"
            key={`w-${choice.weapon}`}
            class={mode.kind === "attack" && mode.weapon === choice.weapon ? "selected" : ""}
            disabled={disabled}
            onClick={() => combat.chooseWeapon(choice.weapon)}
          >
            {tKey(`weapon.${choice.weapon}.name`)} · {choice.apCost}
          </button>
        ))}
        {legal.abilities.map((option) => (
          <button
            type="button"
            key={`a-${option.ability}`}
            class={mode.kind === "ability" && mode.ability === option.ability ? "selected" : ""}
            disabled={disabled}
            onClick={() => combat.chooseAbility(option)}
          >
            {tKey(`ability.${option.ability}.name`)} · {option.ap_cost}
          </button>
        ))}
        {legal.can_wait && (
          <button type="button" disabled={disabled} onClick={() => void combat.act({ type: "wait" })}>
            {t("combat.wait")}
          </button>
        )}
        <button type="button" class="primary" disabled={disabled} onClick={() => void combat.act({ type: "skip" })}>
          {t("combat.skip")}
        </button>
      </div>
    </div>
  );
}
