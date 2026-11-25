import { useEffect, useRef } from "preact/hooks";

import { formatEvent } from "../../combat/log";
import { t } from "../../i18n";
import { combat } from "../../state/combat";

/** Narrated events, newest at the bottom, kept scrolled to the end. */
export function CombatLog() {
  const events = combat.log.value;
  const units = combat.view.value?.units ?? [];
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [events]);

  const lines = events.flatMap((event) => {
    const text = formatEvent(event, units);
    return text ? [{ seq: event.seq, text }] : [];
  });
  return (
    <ol class="combat-log" aria-label={t("combat.log.title")}>
      {lines.map((line) => (
        <li key={line.seq}>{line.text}</li>
      ))}
      <li ref={end} aria-hidden="true" />
    </ol>
  );
}
