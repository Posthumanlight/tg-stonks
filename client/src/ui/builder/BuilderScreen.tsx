import { useState } from "preact/hooks";

import { type Issue, getUnit, unitCard } from "../../builder/draft";
import { sideLabel } from "../../combat/log";
import { t, tError, tKey } from "../../i18n";
import { ApiError, combatApi } from "../../net/api";
import { sideCss } from "../../scenes/combat/palette";
import { builder } from "../../state/builder";
import { goTo } from "../../state/screen";
import { findActiveCombat, openCombat } from "../combat/navigation";
import { DeployPanel } from "./DeployPanel";
import { RosterTray } from "./RosterTray";

/** DOM overlay above the deploy scene (docs/client.md "Custom battle screen"). */
export function BuilderScreen() {
  const state = builder.template.value;
  return (
    <>
      <header class="topbar panel builder-top">
        <div class="row">
          <button type="button" class="icon" onClick={() => goTo("lobby")} aria-label={t("nav.back_to_lobby")}>
            ‹
          </button>
          <h1>{t("builder.title")}</h1>
        </div>
        {state.status === "ready" && <SideTabs />}
      </header>

      {(state.status === "idle" || state.status === "loading") && <p class="note">{t("builder.loading")}</p>}
      {state.status === "error" && (
        <div class="note panel stack" role="alert">
          <p>{t("builder.error")}</p>
          <button type="button" onClick={() => void builder.load()}>
            {t("builder.retry")}
          </button>
        </div>
      )}
      {state.status === "ready" && <Dock />}
    </>
  );
}

function SideTabs() {
  const draft = builder.draft.value;
  const view = builder.view.value;
  const active = builder.activeSide.value;
  const points = builder.points.value;
  if (!draft || !view) return null;
  const factions = draft.sides.map((s) => s.faction);
  return (
    <div class="side-tabs" role="tablist">
      {draft.sides.map((side, index) => (
        <button
          key={index}
          type="button"
          role="tab"
          aria-selected={index === active}
          class={index === active ? "selected" : ""}
          onClick={() => builder.setActiveSide(index)}
        >
          <span class="side-dot" style={{ background: sideCss(index) }} />
          {sideLabel(index, factions)}
          <span class="muted">
            {" "}
            {t("builder.points", { points: points[index] ?? 0 })} ·{" "}
            {t("builder.count", { count: side.units.length, max: view.limits.max_units_per_side })}
          </span>
        </button>
      ))}
    </div>
  );
}

function Dock() {
  const view = builder.view.value;
  const draft = builder.draft.value;
  const side = builder.activeSide.value;
  if (!view || !draft) return null;
  const current = draft.sides[side];

  const changeFaction = (e: Event) => {
    const select = e.currentTarget as HTMLSelectElement;
    if (current && current.units.length > 0 && !window.confirm(t("builder.faction_confirm"))) {
      select.value = current.faction; // keep the controlled value
      return;
    }
    builder.changeFaction(select.value);
  };

  return (
    <section class="builder-dock panel">
      <div class="row">
        <label class="faction-picker">
          <span class="muted">{t("builder.faction")}</span>
          <select value={current?.faction} onChange={changeFaction}>
            {view.factions.map((f) => (
              <option key={f.id} value={f.id}>
                {tKey(f.name_key)}
              </option>
            ))}
          </select>
        </label>
        <Hint />
      </div>
      <DeployPanel />
      <RosterTray />
      <Issues />
      <StartBar />
    </section>
  );
}

function Hint() {
  const notice = builder.notice.value;
  const drag = builder.drag.value;
  const view = builder.view.value;
  if (notice) return <span class="error">{tError(notice)}</span>;
  if (drag.phase === "picked" && drag.source.kind === "roster" && view) {
    const card = unitCard(view, drag.source.unitType);
    return <span class="muted">{t("builder.hint_place", { unit: card ? tKey(card.name_key) : "" })}</span>;
  }
  return <span class="muted">{t("builder.hint")}</span>;
}

/** The hint checks first, then the server's answer to Start. Tapping one selects it. */
function Issues() {
  const issues = builder.issues.value;
  const server = builder.serverIssue.value;
  const all: Issue[] = server ? [...issues, { side: server.side ?? -1, unit: server.unit, reason: server.reason }] : issues;
  if (all.length === 0) return null;
  return (
    <ul class="issues" role="alert">
      {all.map((issue, i) => (
        <li key={i}>
          <button type="button" class="link" onClick={() => focus(issue)}>
            {issueText(issue)}
          </button>
        </li>
      ))}
    </ul>
  );
}

function focus(issue: Issue): void {
  if (issue.side < 0) return;
  builder.setActiveSide(issue.side);
  if (issue.unit !== null) builder.select({ side: issue.side, index: issue.unit });
}

function issueText(issue: Issue): string {
  const reason = tError(issue.reason);
  if (issue.side < 0) return reason;
  const draft = builder.draft.peek();
  const view = builder.view.peek();
  const factions = draft?.sides.map((s) => s.faction);
  const side = sideLabel(issue.side, factions);
  const unit = issue.unit !== null && draft ? getUnit(draft, { side: issue.side, index: issue.unit }) : undefined;
  const card = unit && view ? unitCard(view, unit.unit_type) : undefined;
  if (!card || issue.unit === null) return t("builder.issue", { side, reason });
  return t("builder.issue_unit", { side, unit: `${tKey(card.name_key)} #${issue.unit + 1}`, reason });
}

function StartBar() {
  const canStart = builder.canStart.value;
  const starting = builder.starting.value;
  const conflict = builder.conflict.value;
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setError(null);
    const id = await builder.start();
    if (id) openCombat(id);
  };

  const resolve = async (abandon: boolean) => {
    setError(null);
    try {
      const active = await findActiveCombat();
      if (!abandon) {
        if (active) openCombat(active.combat_id);
        return;
      }
      if (!window.confirm(t("lobby.abandon_confirm"))) return;
      if (active) await combatApi.abandon(active.combat_id);
      await start();
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.reasonKey : "error.generic");
    }
  };

  const reset = () => {
    if (window.confirm(t("builder.reset_confirm"))) builder.resetToDefaults();
  };

  return (
    <div class="stack-tight">
      {conflict && (
        <div class="row">
          <span class="error">{tError("combat.already_active")}</span>
          <button type="button" onClick={() => void resolve(false)}>
            {t("builder.active_resume")}
          </button>
          <button type="button" onClick={() => void resolve(true)}>
            {t("builder.active_abandon")}
          </button>
        </div>
      )}
      {error && <span class="error">{tError(error)}</span>}
      <div class="actions">
        <button type="button" onClick={reset}>
          {t("builder.reset")}
        </button>
        <button type="button" class="primary" disabled={!canStart} onClick={() => void start()}>
          {starting ? t("builder.starting") : t("builder.start")}
        </button>
      </div>
    </div>
  );
}
