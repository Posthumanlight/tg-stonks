import { useEffect, useState } from "preact/hooks";

import { t, tError } from "../../i18n";
import { ApiError, combatApi, roomsApi } from "../../net/api";
import type { CombatSummaryView, RoomJoined } from "../../protocol";
import { currentUser, logout } from "../../state/auth";
import { combat } from "../../state/combat";
import { room } from "../../state/rooms";
import { goTo } from "../../state/screen";
import { listActiveCombats, openCombat } from "../combat/navigation";
import { enterRoom } from "../rooms/navigation";

const reasonOf = (failure: unknown): string =>
  failure instanceof ApiError ? failure.reasonKey : "error.generic";

/** A room code from a shared link (`?room=CODE`), if any. */
const linkedCode = (): string => new URLSearchParams(window.location.search).get("room") ?? "";

/** Main lobby (docs/architecture.md "Lobby"): galaxy chart, hotseat battles, online
 * rooms, and Resume/Abandon (or Surrender) for battles in progress. */
export function Lobby() {
  const user = currentUser.value;
  const closedReason = room.closed.value;
  const [active, setActive] = useState<readonly CombatSummaryView[]>([]);
  const [myRoom, setMyRoom] = useState<RoomJoined | null>(null);
  const [code, setCode] = useState(linkedCode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    listActiveCombats()
      .then((found) => live && setActive(found))
      .catch(() => {}); // the buttons still work; the server enforces the limits
    roomsApi
      .mine()
      .then((mine) => live && setMyRoom(mine.room))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    room.clearClosed();
    try {
      await action();
    } catch (failure) {
      setError(reasonOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const quickBattle = () =>
    run(async () => {
      await combat.openDemo();
      goTo("combat");
    });

  const abandon = (battle: CombatSummaryView) =>
    run(async () => {
      const online = battle.mode === "pvp";
      if (!window.confirm(t(online ? "combat.surrender_confirm" : "lobby.abandon_confirm"))) return;
      await combatApi.abandon(battle.combat_id);
      setActive((list) => list.filter((c) => c.combat_id !== battle.combat_id));
    });

  const joinByCode = (e: Event) => {
    e.preventDefault();
    void run(async () => {
      const joined = await roomsApi.joinByCode(code);
      enterRoom(joined.room_id);
    });
  };

  const hotseat = active.find((c) => c.mode === "hotseat");
  const online = active.find((c) => c.mode === "pvp");

  return (
    <main class="screen-center">
      <section class="panel card stack">
        <header class="row">
          <h1>{t("lobby.title")}</h1>
          <span class="muted">{user?.username}</span>
        </header>
        {closedReason && (
          <p class="error" role="alert">
            {tError(closedReason)}
          </p>
        )}
        <button type="button" class="primary" onClick={() => goTo("galaxy")}>
          {t("lobby.galaxy")}
        </button>

        <h2>{t("lobby.online")}</h2>
        {online ? (
          <ActiveBattle battle={online} busy={busy} label={t("lobby.active_online")} onAbandon={abandon} />
        ) : myRoom ? (
          <button type="button" class="primary" onClick={() => enterRoom(myRoom.room_id)}>
            {t("lobby.back_to_room")}
          </button>
        ) : (
          <>
            <button type="button" disabled={busy} onClick={() => goTo("rooms")}>
              {t("lobby.online_games")}
            </button>
            <form class="row" onSubmit={joinByCode}>
              <input
                value={code}
                maxLength={16}
                autoComplete="off"
                autoCapitalize="characters"
                placeholder={t("lobby.room_code")}
                aria-label={t("lobby.room_code")}
                onInput={(e) => setCode((e.currentTarget as HTMLInputElement).value)}
              />
              <button type="submit" disabled={busy || code.trim() === ""}>
                {t("lobby.join_code")}
              </button>
            </form>
          </>
        )}

        <h2>{t("lobby.hotseat")}</h2>
        {hotseat ? (
          <ActiveBattle battle={hotseat} busy={busy} label={t("lobby.active")} onAbandon={abandon} />
        ) : (
          <>
            <button type="button" disabled={busy} onClick={() => goTo("builder")}>
              {t("lobby.custom_battle")}
            </button>
            <button type="button" disabled={busy} onClick={() => void quickBattle()}>
              {busy ? t("lobby.opening") : t("lobby.quick_battle")}
            </button>
          </>
        )}
        {error && (
          <p class="error" role="alert">
            {tError(error)}
          </p>
        )}
        <button type="button" class="link" onClick={() => void logout()}>
          {t("auth.logout")}
        </button>
      </section>
    </main>
  );
}

function ActiveBattle(props: {
  battle: CombatSummaryView;
  busy: boolean;
  label: string;
  onAbandon: (battle: CombatSummaryView) => Promise<void>;
}) {
  const { battle, busy, label, onAbandon } = props;
  return (
    <div class="stack-tight">
      <p class="muted">{label}</p>
      <div class="row">
        <button type="button" class="primary" disabled={busy} onClick={() => openCombat(battle.combat_id)}>
          {t("lobby.resume")}
        </button>
        <button type="button" disabled={busy} onClick={() => void onAbandon(battle)}>
          {battle.mode === "pvp" ? t("combat.surrender") : t("lobby.abandon")}
        </button>
      </div>
    </div>
  );
}
