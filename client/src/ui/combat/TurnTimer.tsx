import { useEffect, useState } from "preact/hooks";

import { t } from "../../i18n";
import { combat } from "../../state/combat";

const TICK_MS = 250;

/** Seconds left on the active unit's timer (online battles with a timer). */
export function TurnTimer() {
  const deadline = combat.deadline.value;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (deadline === null) return;
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, [deadline]);
  if (deadline === null || combat.view.value?.outcome) return null;
  const seconds = Math.max(0, Math.ceil((deadline - now) / 1000));
  return (
    <span class={seconds <= 10 ? "timer urgent" : "timer"} role="timer" aria-live="off">
      {t("combat.timer", { seconds })}
    </span>
  );
}
