import { useRef } from "preact/hooks";

import { factionCard } from "../../builder/draft";
import { TRAY_ATTR, boardPointer, overTray } from "../../builder/pointer";
import { t, tKey } from "../../i18n";
import type { UnitCard } from "../../protocol";
import { builder } from "../../state/builder";

/** Moves shorter than this (px) are a tap: the card is picked up, then a square tapped. */
const DRAG_SLOP_PX = 8;

/** The active side's faction roster. Cards drag onto the board; tokens dropped back here
 * are removed (the tray is a drop target, see TRAY_ATTR). */
export function RosterTray() {
  const view = builder.view.value;
  const side = builder.draft.value?.sides[builder.activeSide.value];
  const faction = view && side ? factionCard(view, side.faction) : undefined;
  if (!faction) return null;
  return (
    <ul class="roster" {...{ [TRAY_ATTR]: "" }} aria-label={tKey(faction.name_key)}>
      {faction.units.map((card) => (
        <RosterCard key={card.unit_type} card={card} />
      ))}
    </ul>
  );
}

interface Press {
  x: number;
  y: number;
  dragging: boolean;
}

function RosterCard({ card }: { card: UnitCard }) {
  const press = useRef<Press | null>(null);
  const dragged = useRef(false);
  const drag = builder.drag.value;
  const picked =
    drag.phase === "picked" && drag.source.kind === "roster" && drag.source.unitType === card.unit_type;
  const source = { kind: "roster", unitType: card.unit_type } as const;

  const onPointerDown = (e: PointerEvent) => {
    press.current = { x: e.clientX, y: e.clientY, dragging: false };
    dragged.current = false;
    // Capture now: a quick flick leaves the card before its first move event, and
    // without capture that move (and the drag) would go to whatever is underneath.
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: PointerEvent) => {
    const p = press.current;
    if (!p) return;
    if (!p.dragging) {
      const dx = Math.abs(e.clientX - p.x);
      const dy = Math.abs(e.clientY - p.y);
      // Touch: only a mostly vertical move drags (a sideways swipe scrolls the tray).
      const starts = e.pointerType === "mouse" ? Math.max(dx, dy) > DRAG_SLOP_PX : dy > DRAG_SLOP_PX && dy > dx;
      if (!starts) return;
      p.dragging = true;
      builder.beginDrag(source);
    }
    builder.hoverSquare(boardPointer.squareAt(e.clientX, e.clientY));
  };

  const onPointerUp = (e: PointerEvent) => {
    const p = press.current;
    press.current = null;
    if (!p?.dragging) return; // a tap: handled by onClick
    dragged.current = true; // the click that follows this release isn't a tap
    const square = overTray(e.clientX, e.clientY) ? null : boardPointer.squareAt(e.clientX, e.clientY);
    builder.endDrag(square ? { kind: "square", square } : { kind: "none" });
  };

  const onPointerCancel = () => {
    if (press.current?.dragging) builder.endDrag({ kind: "none" });
    press.current = null;
  };

  /** Tap fallback: pick the card up, then tap a square. A click (not pointer events)
   * so keyboards, screen readers and switch access get it too. */
  const onClick = () => {
    if (dragged.current) {
      dragged.current = false;
      return;
    }
    builder.pickUp(source);
  };

  return (
    <li>
      <button
        type="button"
        class={`roster-card${picked ? " selected" : ""}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onClick={onClick}
        aria-pressed={picked}
      >
        <strong>{tKey(card.name_key)}</strong>
        <span class="muted">
          {t("builder.points", { points: card.points })} · {t("builder.footprint", { size: card.footprint })}
        </span>
        <span class="muted">{t("builder.model_range", { min: card.models.min, max: card.models.max })}</span>
      </button>
    </li>
  );
}
