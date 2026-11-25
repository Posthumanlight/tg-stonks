import { useState } from "preact/hooks";

import { t, tError, tKey } from "../../i18n";
import { ApiError } from "../../net/api";
import type { RoomPlayer } from "../../protocol";
import { sideCss } from "../../scenes/combat/palette";
import { builder } from "../../state/builder";
import { room } from "../../state/rooms";
import { Dock } from "../builder/BuilderScreen";
import { pointsText } from "./RoomsScreen";

const reasonOf = (failure: unknown): string => (failure instanceof ApiError ? failure.reasonKey : "error.generic");

/** A lobby room over the deploy scene (docs/client.md "Lobby rooms"): the room header,
 * the opponent's card, and the builder dock for the player's own side with Ready. */
export function RoomScreen() {
  const view = room.room.value;
  const template = builder.template.value;
  const ready = view !== null && template.status === "ready" && builder.mode.value.kind === "room";
  return (
    <>
      <RoomHeader />
      {!ready && <p class="note">{t("room.loading")}</p>}
      {ready && <Dock footer={<ReadyBar />} />}
    </>
  );
}

function RoomHeader() {
  const view = room.room.value;
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const leave = async () => {
    if (!window.confirm(t("room.leave_confirm"))) return;
    try {
      await room.leave(); // the screen follows (main.tsx)
    } catch (failure) {
      setError(reasonOf(failure));
    }
  };
  const copy = async () => {
    if (!view) return;
    try {
      await navigator.clipboard.writeText(view.code);
      setCopied(true);
    } catch {
      setCopied(false); // no clipboard (http, permissions): the code is on screen
    }
  };

  return (
    <header class="topbar panel builder-top">
      <div class="row">
        <button type="button" class="icon" onClick={() => void leave()} aria-label={t("room.leave")}>
          ‹
        </button>
        <h1>{view?.name ?? t("room.title")}</h1>
        {view && (
          <button type="button" class="code" onClick={() => void copy()} aria-label={t("room.copy_code")}>
            {view.code} {copied ? "✓" : ""}
          </button>
        )}
      </div>
      <div class="row opponent">
        <Opponent />
        {view && (
          <span class="muted room-meta">
            {pointsText(view.points_limit)} ·{" "}
            {view.timer_s === 0 ? t("rooms.untimed") : t("combat.timer", { seconds: view.timer_s })}
          </span>
        )}
      </div>
      {error && <span class="error">{tError(error)}</span>}
    </header>
  );
}

function Opponent() {
  const opponent = room.opponent.value;
  const isHost = room.isHost.value;
  const [error, setError] = useState<string | null>(null);
  if (!opponent) return <span class="muted">{t("room.waiting")}</span>;

  const kick = async () => {
    if (!window.confirm(t("room.kick_confirm", { name: opponent.name }))) return;
    try {
      await room.kick();
    } catch (failure) {
      setError(reasonOf(failure));
    }
  };

  return (
    <>
      <span class="side-dot" style={{ background: sideCss(opponent.side) }} />
      <strong>{opponent.name}</strong>
      <span class="muted">{playerStatus(opponent)}</span>
      {isHost && (
        <button type="button" class="link" onClick={() => void kick()}>
          {t("room.kick")}
        </button>
      )}
      {error && <span class="error">{tError(error)}</span>}
    </>
  );
}

function playerStatus(player: RoomPlayer): string {
  if (!player.connected) return t("room.disconnected");
  if (!player.ready || !player.faction) return t("room.deploying");
  return t("room.ready_with", {
    faction: tKey(`faction.${player.faction}.name`),
    points: player.points ?? 0,
    count: player.unit_count ?? 0,
  });
}

/** Ready submits the army (validated by the server); Unready unlocks it. */
function ReadyBar() {
  const me = room.me.value;
  const busy = room.busy.value;
  const canReady = builder.canStart.value;
  const [error, setError] = useState<string | null>(null);
  const side = builder.mode.value.kind === "room" ? builder.mode.value.side : 0;

  const ready = async () => {
    const draft = builder.draft.peek();
    const army = draft?.sides[side];
    if (!army) return;
    setError(null);
    try {
      await room.ready(army); // the battle may start right away (main.tsx follows)
    } catch (failure) {
      builder.reject(failure); // located setup.* issues show in the list
      if (!(failure instanceof ApiError && failure.reasonKey.startsWith("setup."))) setError(reasonOf(failure));
    }
  };
  const unready = async () => {
    setError(null);
    try {
      await room.unready();
    } catch (failure) {
      setError(reasonOf(failure));
    }
  };

  return (
    <div class="stack-tight">
      {error && <span class="error">{tError(error)}</span>}
      <div class="actions">
        {me?.ready ? (
          <button type="button" disabled={busy} onClick={() => void unready()}>
            {t("room.unready")}
          </button>
        ) : (
          <button type="button" class="primary" disabled={busy || !canReady} onClick={() => void ready()}>
            {t("room.ready")}
          </button>
        )}
      </div>
    </div>
  );
}
